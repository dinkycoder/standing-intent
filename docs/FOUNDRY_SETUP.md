# Foundry Setup

This document records the exact steps to set up Foundry and compile `SpendRouter` from the `coinbase/spend-permissions` repository.

## Installation Method: Git Bash (Native Windows)

**Note:** Foundry was successfully installed natively on Windows using Git Bash (MSYS2-based shell), not WSL or PowerShell.

### Step 1: Download and install foundryup

```bash
# In Git Bash:
curl -L https://foundry.paradigm.xyz -o foundry-install.ps1
bash foundry-install.ps1
```

Output:
```
foundryup-init: installing latest foundryup
foundryup-init: downloading attestation...
foundryup-init: verifying binary integrity...
foundryup-init: binary verified ✓
foundryup-init: installing foundryup to /c/Users/dinky/.foundry/bin...
foundryup-init: foundryup was installed successfully!
```

### Step 2: Install Foundry toolchain

```bash
# Add foundry to PATH:
export PATH="$PATH:/c/Users/dinky/.foundry/bin"

# Install Foundry itself (upgraded from v1.7.1 to v1.8.1):
/c/Users/dinky/.foundry/bin/foundryup
```

This installs `forge`, `cast`, `anvil`, `chisel`, and `solar`.

**Final version installed:** `forge 1.8.1 (982849d314 2026-08-28T17:48:03.905115800Z)`

### Step 3: Verify installation

```bash
forge --version
```

Output:
```
forge Version: 1.8.1
Commit SHA: 982849d3140c01fd3b72905759581a132df7aa98
Build Timestamp: 2026-08-28T17:48:03.905115800Z (1787939283)
Build Profile: dist
```

## Clone and Compile SpendRouter

### Step 4: Clone the spend-permissions repository

```bash
cd C:\Users\dinky\projects\standing-intent\.claude\worktrees\week4-spend-permission
git clone https://github.com/coinbase/spend-permissions contracts/spend-router
cd contracts/spend-router
git checkout e0004e63edc4e17de7aa978293800ac7a16892e5
```

**Pinned commit:** `e0004e63edc4e17de7aa978293800ac7a16892e5` (Enable build_info in deploy profile for contract verification #83)

### Step 5: Install Foundry dependencies

```bash
export PATH="$PATH:/c/Users/dinky/.foundry/bin"
forge install
```

This pulls:
- `forge-std`
- `solady`
- `magicspend`
- `openzeppelin-contracts`
- `account-abstraction` (smart-wallet)
- `webauthn-sol`

per the repository's own `foundry.toml` configuration.

### Step 6: Build SpendRouter

```bash
forge build
```

**Build artifact location:** `contracts/spend-router/out/SpendRouter.sol/SpendRouter.json` (131KB)

This JSON file contains:
- The contract ABI (interface definition)
- Deployment bytecode for `SpendRouter`

Task 10 (deployment via AgentKit) will read this artifact to deploy the contract.

## Reproducing This Setup

To reproduce this entire setup from scratch in a fresh clone:

1. Ensure Git Bash (or another POSIX shell on Windows) is available
2. Run the foundryup installer (Step 1 above)
3. Install Foundry (Step 2)
4. Clone the spend-permissions repo at the pinned commit (Step 4)
5. Install dependencies (Step 5)
6. Run `forge build` (Step 6)

**Time to completion:** ~5 minutes on first install (includes downloads and compilation)

## Gotchas and Notes

- **PATH persistence:** The `export PATH="$PATH:/c/Users/dinky/.foundry/bin"` statement only affects the current bash session. Add it to your `.bashrc` if working frequently with Foundry.
- **PowerShell caveat:** The original `irm https://foundry.paradigm.xyz | iex` PowerShell syntax was not used here; native bash execution of the shell script worked without issues.
- **Timeouts:** `forge install` and `forge build` took longer than the default 120-second timeout on first run (network downloads + compilation). Monitoring the output file confirmed both completed successfully.
- **Not a git submodule:** `contracts/spend-router/` is a full clone of an external repo at a pinned commit, left untracked in this repo's git history. This keeps the main repo's commit history clean and independent of upstream changes to spend-permissions.

## References

- **Foundry:** https://github.com/foundry-rs/foundry
- **Foundry Book:** https://book.getfoundry.sh/
- **spend-permissions repo:** https://github.com/coinbase/spend-permissions (pinned at commit `e0004e63edc4e17de7aa978293800ac7a16892e5`)
