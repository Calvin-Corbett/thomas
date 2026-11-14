### Added

- **A Build run that stops responding now shows where it stopped.** Two Build runs went quiet after their final reply and stayed that way for an hour. They had no child process, no network connection and no CPU use, and nothing showed what they were waiting for, so they could only be stopped blind. Every Build runner now writes all its threads' stacks every 20 minutes to a `thomas.log.runner-<pid>.stacks` file in its logs folder, which Export logs includes. A runner that finishes normally removes its file, so a file that stays marks a runner that was stopped or hung.
