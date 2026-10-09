# Backing up the hub

The hub is a git repository. `cc-hub` commits what its own commands change,
and the agent commits after each task that changed files in the hub. Nothing
leaves the machine until you add a remote; from then on the nightly
memory-consolidate task pushes.

The hub holds `USER.md`, `MEMORY.md`, the daily logs and app data, so the
remote must be a **private** repository.

## Set up a remote

1. Create an empty private repository without a README, for example
   `you/my-hub` on GitHub.
2. On the machine that runs the hub, create a key that can write to that one
   repository:

       ssh-keygen -t ed25519 -f ~/.ssh/cc-hub-backup -N "" -C "cc-hub backup"

   Add `~/.ssh/cc-hub-backup.pub` to the repository as a deploy key with
   write access (GitHub: Settings → Deploy keys).
3. Point the hub at it and push once:

       git -C ~/.cc-hub remote add origin git@github.com:you/my-hub.git
       git -C ~/.cc-hub config core.sshCommand "ssh -i ~/.ssh/cc-hub-backup -o IdentitiesOnly=yes"
       git -C ~/.cc-hub push -u origin HEAD

`cc-hub doctor` stops reporting "no remote" once `origin` exists.

## When a push is rejected

A rejected push means the remote has commits this machine does not, usually
because the hub ran somewhere else too. The agent does not pull or merge; it
logs the rejection and reports it. Run the hub on one machine at a time, and
reconcile by hand with `git pull --rebase` or by choosing one side.
