### Changed

- **The recent-chats list draws about four times faster.** You asked for everything to feel snappy. Timing a real page load showed one script, the sidebar's, taking 400 milliseconds, ten times any other, because it built a new date formatter for each of the several hundred rows. It now builds each kind once; the dates read the same.
