from typing import Any

import numpy as np
from numpy.typing import NDArray

type IntArray = NDArray[np.int_]
type BoolArray = NDArray[np.bool_]
type FloatArray = NDArray[np.floating[Any]]
type UInt8Array = NDArray[np.uint8]
type Pair = tuple[int, int, int, int]  # (area label, y, x, dx): pixel (y, x) links to (y + 1, x + dx)

#: Edge neighbours in the order every scan in the package uses (the order matters for tie-breaking).
NEIGHBOURS_4 = ((1, 0), (-1, 0), (0, 1), (0, -1))
DIAGONALS = ((1, 1), (1, -1), (-1, 1), (-1, -1))
