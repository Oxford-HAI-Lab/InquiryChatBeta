# read_code of the Database node `session`: emit the record the last write left.
result = state.get("out", "@@KIND FAULT\nno record")
