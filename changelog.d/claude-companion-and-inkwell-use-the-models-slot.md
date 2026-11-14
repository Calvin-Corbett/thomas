### Changed

- The companion app generator, the companion ask route and Inkwell's note analysis now get their model from the shared models slot, and the generator and ask route close the model client when they finish, so you no longer leave a client open after each request.
