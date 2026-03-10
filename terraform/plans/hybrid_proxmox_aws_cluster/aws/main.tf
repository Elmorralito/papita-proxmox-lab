terraform {
  required_version = ">=1.6.5, <2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.28"
    }

    tailscale = {
      source  = "tailscale/tailscale"
      version = "~> 0.13"
    }

    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.7.0"
    }

    null = {
      source  = "hashicorp/null"
      version = "~> 3.2.3"
    }

    external = {
      source  = "hashicorp/external"
      version = "~> 2.3.5" # Specify your desired version constraint here
    }

    local = {
      source  = "hashicorp/local"
      version = "~> 2.5.3"
    }

    random = {
      source  = "hashicorp/random"
      version = "~> 3.8.1"
    }
  }
}
