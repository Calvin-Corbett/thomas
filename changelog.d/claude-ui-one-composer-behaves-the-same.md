### Fixed

- **Work no longer loses a message you send while it is still answering.** It used to drop the message and clear the box. The message now waits in view, marked "queued", and goes out when the reply ends. If you open another job first, it is named as not sent, never sent to the wrong job.
- **Files you attach in Work are sent with the message.** They were ignored and their chips cleared.
- **The box clears only when the mode took the message.** The shell used to report success whatever the mode did.
- **Escape on an empty box stops a running reply in Work**, as it already did in Build. Enter that picks a word in Japanese, Chinese or Korean input no longer sends.
- **The "/" commands and the checklist attach to the composer in every mode.** They looked for it by its placeholder, so they missed Work, and in Build could attach to the side drawer's box.
- **The "+" menu offers image, music and video only in Chat.** In Build and Work those items did nothing and said nothing.
- **Build's Pause, Resume and Stop keep their own tooltip.** A sync after each keystroke was writing "Send" over it.

You said: "I'm pretty sure we kind of standardized the composer. We should just use the same one."
