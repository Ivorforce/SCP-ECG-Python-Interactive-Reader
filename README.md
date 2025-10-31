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

    # Get the record description tags
    print(file.section1().read_tags_and_interpret())

    # Get the beat measurements
    print(file.section7().read())

    # Plot the data
    import plotly.express as px
    import pandas as pd
    px.line(file.section6_dataframe())
```