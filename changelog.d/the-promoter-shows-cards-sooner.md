### Changed
- The self-change promoter checks whether a change touches a gate file with one git call instead of two per gate file. That check took about 9 s before every card and now takes a quarter of a second, with the same verdicts (identical on the last 60 commits of dev, refusals included). If git cannot answer in one call, it asks file by file as before.
- After a card is answered, the promoter looks for the next waiting change straight away instead of pausing 3 seconds first. It still pauses when nothing is waiting, when a change was taken back out, or when a pass failed.
