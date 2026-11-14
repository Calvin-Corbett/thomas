### Changed

- The old chat engine is deleted: nothing in the running server reached it, because Chat V2 answers `/api/chat` and the V1 route was never registered. That removes the last place Thomas opened a model client by hand, so every model client now comes from the models slot, and you will see no change in how chat behaves.
