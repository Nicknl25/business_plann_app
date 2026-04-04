# Git Setup

## Repo Defaults
- Remote: `git@github.com:Nicknl25/business_plann_app.git`
- Main working branch in this repo: `intake-stable`
- Expected transport: SSH, not HTTPS

## New Machine Checklist
1. Install Git.
2. Set Git identity:
   - `git config --global user.name "<your name>"`
   - `git config --global user.email "<your email>"`
3. Generate or copy an SSH key for the machine.
4. Add the public key to the GitHub account that has access to this repo.
5. Ensure the SSH agent is running and the key is loaded.
6. Verify access:
   - `ssh -T git@github.com`
   - `git fetch origin`

## Repo Verification
- Confirm remote is still SSH:
  - `git remote -v`
- Confirm branch:
  - `git branch --show-current`
- If needed, reset `origin` to SSH:
  - `git remote set-url origin git@github.com:Nicknl25/business_plann_app.git`

## Expected Push Flow
- Work on `intake-stable` unless intentionally creating another branch.
- Standard sequence:
  - `git status`
  - `git add ...`
  - `git commit -m "message"`
  - `git push origin intake-stable`

## If Push Fails
- First check SSH auth, not Git logic.
- Typical causes:
  - key not added to GitHub
  - key not loaded in agent
  - wrong GitHub account
  - remote changed to HTTPS

## Codex Note
- If machine-level SSH auth works, Codex can use normal `git` commands without special repo changes.
- Git access problems on a new machine are almost always environment/auth issues, not project issues.
