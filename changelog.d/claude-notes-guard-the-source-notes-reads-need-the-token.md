### Security

- **A caller on another machine now needs your api token to read the notes on your source, or the source itself.** In remote mode the two reads under `/api/source-annotations` answered anyone, and the second one returned any file under the workspace root; only the three writes were refused. Every one of the five routes now runs the same access guard the other workspace routes run, before it touches the request. On this machine nothing changes.
