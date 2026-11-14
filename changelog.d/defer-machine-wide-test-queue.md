### Changed

- Your requested scope excludes item (2), the machine-wide test queue: "do not add a test queue and do not change how check.run or the precard shards wait."
- Items (1), (3), (4), and (5) remain requested, with item (5) to build on the queue once it has landed. Their original definitions are not present in the supplied conversation, so this fragment records the scope change, not completion of those items.
- This change contains no runtime implementation and does not change the queue, check runner, or precard waiting behavior.

### Verification limitation

- On local baseline `b123785c41945b9d24a249249bb8faf74a4dfb80`, the three reported sandbox-launch and plugin-fence tests finished with failures. Their test IDs and failure assertions matched the run with the prior Markdown-only change; they were not merely assumed to be baseline failures because an earlier run timed out.
- The unchanged-baseline run also passed all 13 architecture tests. These results do not repair the three failures or establish completion of the undefined numbered items.
