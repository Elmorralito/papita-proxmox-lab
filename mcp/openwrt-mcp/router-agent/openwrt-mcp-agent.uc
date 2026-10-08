#!/usr/bin/ucode
// openwrt-mcp router agent (protocol v1). See docs/AGENT_CONTRACT.md.
//
// Forced SSH command: reads ONE JSON object from stdin, writes ONE JSON object to stdout.
// Nothing from the request is ever interpolated into a shell. Every field is re-authorized here,
// independently of the MCP service (defense in depth).
//
// Local modes (root shell / procd only):  --watchdog-tick   --clear
'use strict';

import * as fs from 'fs';
import * as uci from 'uci';
import { sha256, sha256_file } from 'digest';

const VERSION = '0.1.0';
const PROTOCOL = 1;
const POLICY_REVISION = 1;
const CONF = '/etc/config/firewall';
const PERSIST = '/etc/openwrt-mcp';
const JOURNAL = PERSIST + '/journal';
const USED = PERSIST + '/used';
const PUBKEY = PERSIST + '/approver.pub';
const RUN = '/var/run/openwrt-mcp';
const HEARTBEAT = RUN + '/watchdog.alive';
const LOCKFILE = RUN + '/lock';
const ACTIVE = JOURNAL + '/active.json';
const LAST = JOURNAL + '/last.json';
const PREFIX = 'mcp_';
const OWNER = 'openwrt-mcp';
const MAX_REQUEST = 65536;
const HEARTBEAT_MAX_AGE = 15;
const APPLY_BUDGET = 90;
const PROHIBITED_PORTS = [22, 53, 80, 443, 41641];
const CLOCK_FLOOR = 1735689600; // 2025-01-01

// ---------------------------------------------------------------- helpers

function fail(code, message) {
	die(code + '|' + message);
}

function ensure_dirs() {
	for (let d in [PERSIST, JOURNAL, USED, RUN])
		fs.mkdir(d, 0700);
}

function uptime() {
	let u = fs.readfile('/proc/uptime');
	return u ? int(split(trim(u), ' ')[0]) : 0;
}

function boot_id() {
	let b = fs.readfile('/proc/sys/kernel/random/boot_id');
	return b ? trim(b) : 'unknown';
}

function revision() {
	let h = sha256_file(CONF);
	return h ? 'sha256:' + h : null;
}

function read_json(path) {
	let s = fs.readfile(path);
	if (!s)
		return null;
	try {
		return json(s);
	}
	catch (e) {
		return null;
	}
}

function write_json(path, obj) {
	let tmp = path + '.tmp';
	if (fs.writefile(tmp, sprintf('%J', obj)) == null)
		fail('APPLY_FAILED', 'cannot write journal');
	fs.rename(tmp, path);
}

// Run argv (constants and generated/validated tokens only) with a timeout. The constant wrapper script
// discards stdout/stderr so child processes can never corrupt the JSON on stdout; argv is passed as
// positional parameters, not interpolated. Returns the exit code (non-zero on timeout).
function run(argv, timeout_ms) {
	let full = ['/bin/sh', '-c', 'exec "$@" >/dev/null 2>&1', 'sh'];
	for (let a in argv)
		push(full, a);
	return system(full, timeout_ms);
}

function section_for(rule_id) {
	return PREFIX + replace(rule_id, '-', '_');
}

function id_for(section) {
	return replace(substr(section, length(PREFIX)), '_', '-');
}

function canon(v) {
	let t = type(v);
	if (t == 'bool')
		return v ? 'true' : 'false';
	if (t == 'int')
		return sprintf('%d', v);
	if (t == 'string') {
		if (!match(v, /^[A-Za-z0-9_.\/:@-]*$/))
			die('BAD_REQUEST|unsafe string in canonical JSON');
		return '"' + v + '"';
	}
	if (t == 'array')
		return '[' + join(',', map(v, (x) => canon(x))) + ']';
	if (t == 'object') {
		let ks = sort(keys(v));
		return '{' + join(',', map(ks, (k) => canon(k) + ':' + canon(v[k]))) + '}';
	}
	die('BAD_REQUEST|unsupported type in canonical JSON');
}

function only_keys(obj, allowed, what) {
	if (type(obj) != 'object')
		fail('BAD_REQUEST', what + ' must be an object');
	for (let k in obj)
		if (index(allowed, k) < 0)
			fail('BAD_REQUEST', 'unknown field in ' + what + ': ' + k);
}

// ---------------------------------------------------------------- authorization (allowlist)

function valid_src_ip(v) {
	let m = match(v, /^172\.16\.([0-9]{1,3})\.([0-9]{1,3})\/([0-9]{1,2})$/);
	if (!m)
		return false;
	return int(m[1]) <= 255 && int(m[2]) <= 255 && int(m[3]) >= 16 && int(m[3]) <= 32;
}

function validate_ops(ops) {
	if (type(ops) != 'array' || length(ops) < 1 || length(ops) > 5)
		fail('BAD_REQUEST', 'operations must be an array of 1..5 items');
	let seen = {};
	for (let op in ops) {
		if (type(op) != 'object' || type(op.type) != 'string')
			fail('BAD_REQUEST', 'malformed operation');
		if (type(op.rule_id) != 'string' || !match(op.rule_id, /^[a-z0-9][a-z0-9-]{0,31}$/))
			fail('BAD_REQUEST', 'invalid rule_id');
		if (seen[op.rule_id])
			fail('BAD_REQUEST', 'duplicate rule_id in plan');
		seen[op.rule_id] = true;
		if (op.type == 'firewall.rule.delete') {
			only_keys(op, ['type', 'rule_id'], 'operation');
		}
		else if (op.type == 'firewall.rule.upsert') {
			only_keys(op, ['type', 'rule_id', 'fields'], 'operation');
			let f = op.fields;
			only_keys(f, ['template', 'src', 'proto', 'dest_port', 'family', 'src_ip'], 'fields');
			if (f.template != 'allow_tcp_from_lan')
				fail('OPERATION_PROHIBITED', 'unsupported template');
			if (f.src != 'lan')
				fail('OPERATION_PROHIBITED', 'src must be lan');
			if (f.proto != 'tcp')
				fail('OPERATION_PROHIBITED', 'proto must be tcp');
			if (type(f.dest_port) != 'int' || f.dest_port < 1 || f.dest_port > 65535)
				fail('BAD_REQUEST', 'invalid dest_port');
			if (index(PROHIBITED_PORTS, f.dest_port) >= 0)
				fail('OPERATION_PROHIBITED', 'port is prohibited');
			if (index(['ipv4', 'ipv6', 'any'], f.family) < 0)
				fail('BAD_REQUEST', 'invalid family');
			if (f.src_ip != null && (type(f.src_ip) != 'string' || !valid_src_ip(f.src_ip)))
				fail('OPERATION_PROHIBITED', 'src_ip must be inside 172.16.0.0/16');
		}
		else
			fail('OPERATION_PROHIBITED', 'unsupported operation type');
	}
	return ops;
}

// ---------------------------------------------------------------- journal / watchdog state

function active_journal() {
	return read_json(ACTIVE);
}

function archive_journal(j, state) {
	j.state = state;
	write_json(LAST, j);
	fs.unlink(ACTIVE);
}

function watchdog_alive() {
	let hb = fs.readfile(HEARTBEAT);
	if (!hb)
		return false;
	let age = uptime() - int(split(trim(hb), ' ')[0]);
	return age >= 0 && age <= HEARTBEAT_MAX_AGE;
}

function clock_ok() {
	return time() > CLOCK_FLOOR;
}

function take_lock(blocking) {
	let lk = fs.open(LOCKFILE, 'w');
	if (!lk)
		fail('APPLY_FAILED', 'cannot open lock');
	if (!lk.lock(blocking ? 'x' : 'xn'))
		return null;
	return lk;
}

// ---------------------------------------------------------------- inspection

function owned_rules(cur) {
	let out = [];
	cur.foreach('firewall', 'rule', (s) => {
		let name = s['.name'];
		if (substr(name, 0, length(PREFIX)) != PREFIX || s.owned_by != OWNER)
			return;
		let r = {
			id: id_for(name),
			section: name,
			enabled: s.enabled != '0',
			src: s.src,
			proto: type(s.proto) == 'array' ? s.proto[0] : s.proto,
			dest_port: int(s.dest_port),
			family: s.family ?? 'any'
		};
		if (s.src_ip)
			r.src_ip = type(s.src_ip) == 'array' ? s.src_ip[0] : s.src_ip;
		push(out, r);
	});
	return out;
}

function nft_state() {
	let p = fs.popen('/usr/sbin/nft list table inet fw4 2>/dev/null', 'r');
	if (!p)
		return { loaded: false, rules: [] };
	let text = p.read('all') ?? '';
	p.close();
	let rules = [];
	let seen = {};
	for (let m in match(text, /comment "!fw4: (mcp_[a-z0-9_]+)"/g) ?? []) {
		let name = type(m) == 'array' ? m[1] : m;
		if (!seen[name]) {
			seen[name] = true;
			push(rules, name);
		}
	}
	return { loaded: length(text) > 0, rules: rules };
}

function pending_changes(cur) {
	let ch = cur.changes('firewall');
	return ch != null && length(keys(ch)) > 0 && length(ch['firewall'] ?? []) > 0;
}

function op_inspect() {
	let cur = uci.cursor();
	let rules = owned_rules(cur);
	let nft = nft_state();
	let wan = false;
	for (let r in rules)
		if (r.src != 'lan')
			wan = true;
	let j = active_journal();
	return {
		ok: true,
		v: PROTOCOL,
		agent_version: VERSION,
		config_revision: revision(),
		agent_owned_rules: rules,
		pending_changes: pending_changes(cur),
		nft_loaded: nft.loaded,
		nft_rules: nft.rules,
		wan_exposure: wan,
		watchdog_alive: watchdog_alive(),
		active_txn: j ? j.plan_id : null,
		tailscale_running: run(['/bin/pidof', 'tailscaled'], 5000) == 0,
		clock_ok: clock_ok()
	};
}

// ---------------------------------------------------------------- mutation

function stage_ops(cur, ops) {
	for (let op in ops) {
		let sect = section_for(op.rule_id);
		let existing = cur.get_all('firewall', sect);
		if (existing != null && (existing.owned_by != OWNER))
			fail('OPERATION_PROHIBITED', 'section is not agent-owned: ' + sect);
		if (op.type == 'firewall.rule.delete') {
			if (existing == null)
				fail('VALIDATION_FAILED', 'rule does not exist: ' + op.rule_id);
			cur.delete('firewall', sect);
			continue;
		}
		if (existing != null)
			cur.delete('firewall', sect);
		let f = op.fields;
		cur.set('firewall', sect, 'rule');
		cur.set('firewall', sect, 'name', sect);
		cur.set('firewall', sect, 'owned_by', OWNER);
		cur.set('firewall', sect, 'src', f.src);
		cur.set('firewall', sect, 'proto', f.proto);
		cur.set('firewall', sect, 'dest_port', sprintf('%d', f.dest_port));
		cur.set('firewall', sect, 'target', 'ACCEPT');
		if (f.family != 'any')
			cur.set('firewall', sect, 'family', f.family);
		if (f.src_ip != null)
			cur.set('firewall', sect, 'src_ip', f.src_ip);
	}
}

function restore_backup(path) {
	let data = fs.readfile(path);
	if (data == null)
		return false;
	let tmp = CONF + '.owrt.tmp';
	if (fs.writefile(tmp, data) == null)
		return false;
	return fs.rename(tmp, CONF) != null;
}

// Roll back the active journal. Refuses (NEEDS_MANUAL) to overwrite a config that drifted.
function do_rollback(j, reason) {
	let cur_rev = revision();
	if (cur_rev != j.new_revision && cur_rev != j.pre_revision) {
		j.state = 'needs_manual';
		j.reason = 'config drifted during transaction; not overwriting';
		write_json(ACTIVE, j);
		fail('NEEDS_MANUAL', j.reason);
	}
	if (cur_rev != j.pre_revision) {
		if (!restore_backup(j.backup))
			fail('APPLY_FAILED', 'cannot restore backup');
		let cur = uci.cursor();
		cur.revert('firewall');
		run(['/sbin/fw4', '-q', 'reload'], 60000);
	}
	j.reason = reason;
	archive_journal(j, 'rolled_back');
	return { ok: true, v: PROTOCOL, state: 'rolled_back', reason: reason };
}

function verify_grant(req) {
	let g = req.grant;
	only_keys(g, ['payload', 'signature'], 'grant');
	if (type(g.payload) != 'string' || type(g.signature) != 'string' || length(g.payload) > 4096 || length(g.signature) > 512)
		fail('APPROVAL_INVALID', 'malformed grant');
	let tag = sprintf('%d', time()) + '.' + sprintf('%d', uptime());
	let msg = RUN + '/grant.' + tag + '.msg';
	let sig = RUN + '/grant.' + tag + '.sig';
	fs.writefile(msg, g.payload);
	fs.writefile(sig, g.signature);
	let rc = run(['/usr/bin/usign', '-V', '-m', msg, '-p', PUBKEY, '-x', sig], 10000);
	fs.unlink(msg);
	fs.unlink(sig);
	if (rc != 0)
		fail('APPROVAL_INVALID', 'grant signature verification failed');

	let p;
	try {
		p = json(g.payload);
	}
	catch (e) {
		fail('APPROVAL_INVALID', 'grant payload is not JSON');
	}
	if (canon(p) != g.payload)
		fail('APPROVAL_INVALID', 'grant payload is not canonical');
	let bound = {
		plan_id: req.plan_id,
		plan_digest: req.plan_digest,
		state_precondition: req.state_precondition,
		router_id: req.router_id,
		policy_revision: req.policy_revision
	};
	for (let k, v in bound)
		if (p[k] != v)
			fail('APPROVAL_INVALID', 'grant is not bound to this plan: ' + k);
	if (type(p.expires_at) != 'int' || p.expires_at <= time())
		fail('APPROVAL_EXPIRED', 'grant expired');
	if (type(p.nonce) != 'string' || !match(p.nonce, /^[0-9a-f]{16}$/))
		fail('APPROVAL_INVALID', 'invalid nonce');
	let used = USED + '/' + p.nonce;
	if (fs.stat(used))
		fail('APPROVAL_INVALID', 'grant already used');
	fs.writefile(used, sprintf('%d', time()));
}

function op_apply(req) {
	only_keys(req, ['v', 'op', 'plan_id', 'plan_digest', 'router_id', 'policy_revision', 'state_precondition',
		'operations', 'recovery', 'grant'], 'request');
	if (type(req.plan_id) != 'string' || !match(req.plan_id, /^plan_[0-9a-f]{8}$/))
		fail('BAD_REQUEST', 'invalid plan_id');
	only_keys(req.recovery, ['mode', 'deadline_s'], 'recovery');
	if (req.recovery.mode != 'auto_revert' || type(req.recovery.deadline_s) != 'int'
	    || req.recovery.deadline_s < 30 || req.recovery.deadline_s > 300)
		fail('BAD_REQUEST', 'recovery must be auto_revert with deadline_s 30..300');
	if (req.policy_revision != POLICY_REVISION)
		fail('APPROVAL_INVALID', 'policy revision mismatch');
	if (!clock_ok())
		fail('CLOCK_UNSYNCED', 'router clock is not synchronised');

	let digest = 'sha256:' + sha256(canon({
		router_id: req.router_id,
		operations: req.operations,
		state_precondition: req.state_precondition,
		policy_revision: req.policy_revision,
		recovery: req.recovery
	}));
	if (digest != req.plan_digest)
		fail('APPROVAL_INVALID', 'plan digest does not match request contents');
	let ops = validate_ops(req.operations);

	let lk = take_lock(false);
	if (!lk)
		fail('TARGET_LOCKED', 'another agent invocation is running');
	let existing = active_journal();
	if (existing)
		fail('TARGET_LOCKED', 'transaction ' + existing.plan_id + ' is active (' + existing.state + ')');

	verify_grant(req);

	let cur = uci.cursor();
	if (pending_changes(cur))
		fail('TARGET_LOCKED', 'uncommitted UCI changes exist');
	let pre = revision();
	if (pre != req.state_precondition)
		fail('STATE_PRECONDITION_FAILED', 'configuration changed since planning');
	if (!watchdog_alive())
		fail('WATCHDOG_UNAVAILABLE', 'independent watchdog is not running; refusing to mutate');

	// Arm: persistent backup + journal BEFORE any change.
	let backup = JOURNAL + '/' + req.plan_id + '.firewall.bak';
	let data = fs.readfile(CONF);
	if (data == null || fs.writefile(backup, data) == null)
		fail('APPLY_FAILED', 'cannot write backup');
	let j = {
		plan_id: req.plan_id,
		journal_id: 'j-' + substr(req.plan_id, 5),
		state: 'armed',
		backup: backup,
		pre_revision: pre,
		new_revision: null,
		boot_id: boot_id(),
		deadline_uptime: uptime() + req.recovery.deadline_s + APPLY_BUDGET,
		deadline_s: req.recovery.deadline_s,
		created: time()
	};
	write_json(ACTIVE, j);

	stage_ops(cur, ops);
	cur.save('firewall');
	cur.commit('firewall');
	// Record the resulting revision immediately so a failure from here on is recognised as OUR change
	// (rollback refuses to overwrite a config that matches neither the pre- nor post-change revision).
	j.new_revision = revision();
	write_json(ACTIVE, j);

	if (run(['/sbin/fw4', '-q', 'check'], 30000) != 0) {
		restore_backup(backup);
		cur = uci.cursor();
		cur.revert('firewall');
		archive_journal(j, 'rolled_back');
		fail('VALIDATION_FAILED', 'fw4 check rejected the candidate; nothing was loaded');
	}
	if (run(['/sbin/fw4', '-q', 'reload'], 60000) != 0) {
		do_rollback(j, 'reload failed');
		fail('APPLY_FAILED', 'fw4 reload failed; rolled back');
	}

	j.new_revision = revision();
	j.state = 'applied_unconfirmed';
	j.deadline_uptime = uptime() + req.recovery.deadline_s;
	write_json(ACTIVE, j);
	return {
		ok: true,
		v: PROTOCOL,
		state: 'applied_unconfirmed',
		journal_id: j.journal_id,
		backup: 'persisted',
		new_revision: j.new_revision,
		verify_deadline_s: req.recovery.deadline_s
	};
}

function op_validate(req) {
	only_keys(req, ['v', 'op', 'operations', 'state_precondition'], 'request');
	let ops = validate_ops(req.operations);
	let lk = take_lock(false);
	if (!lk)
		fail('TARGET_LOCKED', 'another agent invocation is running');
	if (active_journal())
		fail('TARGET_LOCKED', 'a transaction is active');
	let cur = uci.cursor();
	if (pending_changes(cur))
		fail('TARGET_LOCKED', 'uncommitted UCI changes exist');
	if (revision() != req.state_precondition)
		fail('STATE_PRECONDITION_FAILED', 'configuration changed since planning');
	// Stage (uncommitted delta), check, always revert.
	let ok = false;
	try {
		stage_ops(cur, ops);
		cur.save('firewall');
		ok = run(['/sbin/fw4', '-q', 'check'], 30000) == 0;
	}
	catch (e) {
		cur.revert('firewall');
		die(e.message);
	}
	cur.revert('firewall');
	if (!ok)
		fail('VALIDATION_FAILED', 'fw4 check rejected the candidate');
	return { ok: true, v: PROTOCOL, valid: true, candidate_ok: true };
}

function find_journal(plan_id) {
	let j = active_journal();
	if (j && j.plan_id == plan_id)
		return j;
	let l = read_json(LAST);
	if (l && l.plan_id == plan_id)
		return l;
	return null;
}

function op_confirm(req) {
	only_keys(req, ['v', 'op', 'plan_id'], 'request');
	let lk = take_lock(false);
	if (!lk)
		fail('TARGET_LOCKED', 'another agent invocation is running');
	let j = active_journal();
	if (!j || j.plan_id != req.plan_id)
		fail('NOT_FOUND', 'no active transaction for plan');
	if (j.state != 'applied_unconfirmed')
		fail('VALIDATION_FAILED', 'transaction is ' + j.state);
	if (j.boot_id != boot_id() || uptime() >= j.deadline_uptime) {
		do_rollback(j, 'confirmation deadline passed');
		fail('VALIDATION_FAILED', 'deadline passed; rolled back');
	}
	archive_journal(j, 'confirmed');
	return { ok: true, v: PROTOCOL, state: 'confirmed' };
}

function op_rollback(req) {
	only_keys(req, ['v', 'op', 'plan_id'], 'request');
	let lk = take_lock(true);
	let j = active_journal();
	if (!j || j.plan_id != req.plan_id)
		fail('NOT_FOUND', 'no active transaction for plan');
	return do_rollback(j, 'operator rollback');
}

function op_status(req) {
	only_keys(req, ['v', 'op', 'plan_id'], 'request');
	if (req.plan_id == null) {
		let j = active_journal();
		return { ok: true, v: PROTOCOL, state: j ? j.state : 'idle', plan_id: j ? j.plan_id : null };
	}
	let j = find_journal(req.plan_id);
	if (!j)
		fail('NOT_FOUND', 'no journal for plan');
	return { ok: true, v: PROTOCOL, state: j.state, plan_id: j.plan_id, new_revision: j.new_revision,
		journal_id: j.journal_id, reason: j.reason };
}

// ---------------------------------------------------------------- local modes

function watchdog_tick() {
	let lk = take_lock(false);
	if (!lk)
		return;
	let j = active_journal();
	if (!j || (j.state != 'applied_unconfirmed' && j.state != 'armed'))
		return;
	if (j.boot_id != boot_id() || uptime() >= j.deadline_uptime) {
		try {
			do_rollback(j, j.boot_id != boot_id() ? 'unconfirmed across reboot' : 'confirmation deadline passed');
		}
		catch (e) {
			// NEEDS_MANUAL is recorded in the journal; keep the heartbeat loop alive.
		}
	}
}

function main() {
	ensure_dirs();
	if (length(ARGV) > 0) {
		if (ARGV[0] == '--watchdog-tick') {
			watchdog_tick();
			return 0;
		}
		if (ARGV[0] == '--clear') {
			let j = active_journal();
			if (j && j.state == 'needs_manual')
				archive_journal(j, 'cleared_manually');
			return 0;
		}
		warn('unknown argument\n');
		return 2;
	}

	let raw = fs.stdin.read(MAX_REQUEST + 1);
	let resp;
	try {
		if (!raw || length(raw) > MAX_REQUEST)
			fail('BAD_REQUEST', 'empty or oversized request');
		let req = json(raw);
		if (type(req) != 'object' || req.v != PROTOCOL || type(req.op) != 'string')
			fail('BAD_REQUEST', 'malformed request envelope');
		if (req.op == 'inspect') {
			only_keys(req, ['v', 'op'], 'request');
			resp = op_inspect();
		}
		else if (req.op == 'validate')
			resp = op_validate(req);
		else if (req.op == 'apply')
			resp = op_apply(req);
		else if (req.op == 'confirm')
			resp = op_confirm(req);
		else if (req.op == 'rollback')
			resp = op_rollback(req);
		else if (req.op == 'status')
			resp = op_status(req);
		else
			fail('BAD_REQUEST', 'unknown op');
	}
	catch (e) {
		let m = match(e.message ?? '', /^([A-Z_]+)\|(.*)$/);
		resp = {
			ok: false,
			v: PROTOCOL,
			error: m ? { code: m[1], message: m[2] } : { code: 'BAD_REQUEST', message: 'invalid request' }
		};
	}
	print(sprintf('%J', resp), '\n');
	return 0;
}

exit(main());
