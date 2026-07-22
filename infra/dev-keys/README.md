# Dev RS256 keypair

`rs256-private.pem` / `rs256-public.pem` are a fixed, committed 4096-bit RSA
keypair used only for local dev and tests (`make dev`, `make test`, CI). Not
sensitive — equivalent in posture to the old hardcoded dev JWT secret.

Real production key material must never be committed here. It comes from AWS
Secrets Manager (see the Terraform module, once written) and is injected into
each ECS task's environment at deploy time.
