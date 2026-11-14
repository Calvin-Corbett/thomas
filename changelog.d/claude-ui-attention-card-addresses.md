### Security

- **A card can no longer be pointed at another site with a trick address.** A picture or preview on a card must come from Thomas or from this PC, and that was checked by how the address began. A browser reads a backslash as a slash and drops tabs and line breaks, so an address such as `/\example.com/x` passed the check and left this PC. The address is now parsed the way a browser reads it, and one with a backslash, a tab, a line break, a user name or any other host is refused.
