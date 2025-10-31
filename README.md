# SCP-ECG Python file reader

A file reader for [SCP-ECG](https://en.wikipedia.org/wiki/SCP-ECG) files, written in Python.

The reader is made to be interactive, such that information can be extracted using scripts made on top of the reader.

Since there exists no detailed information about the reader at this point, I recommend browsing the methods of `SCPFile` to understand this repository.

## Example usage

```python
from scp_ecg_file import SCPFile
import pathlib

with pathlib.Path("record.scp").open("rb") as f:
    file = SCPFile.read(f)

    # Get meta information about the headers (for debug purposes)
    print(file.read_all_section_headers())

    # Get the record description tags
    print(file.section1().read_tags_and_interpret())

    # Get the beat measurements
    print(file.section7().read())

    # Plot the data
    import plotly.express as px
    import pandas as pd
    px.line(file.section6_dataframe())

    # Convert the data to the MIT-BIH file format
    import plotly.express as px
    import pandas as pd
    file.write_wfdb_file("destination/path/record")
```

## Supported Features

SCP-ECG is a fairly complex, highly engineered file type. Support for sections has to be added one by one.
The support in this implementation is need-directed, and thus a lot of features are not supported yet. I am open to and interested in adding support for new features when it is useful for other people.

- SCPFile / Section 0: Used for navigating the file.
- Section 1: Contains record description tags.
- Section 2: May contain huffman tables to read the file. This is not fully supported yet (some files are not encoded with huffman tables).
- Section 3: Contains lead information.
- Section 6: Contains ECG data.
- Section 7: Contains ECG per beat metadata.
- Section 10: Contains global ECG metadata.
