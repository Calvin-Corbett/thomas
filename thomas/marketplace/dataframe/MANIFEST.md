# Thomas DataFrame Library - Complete Manifest

## Project Structure

```
thomas/dataframe/
├── Core Library Files
│   ├── __init__.py              - Public API exports
│   ├── _types.py                - Type system & enumerations
│   ├── _exceptions.py           - Custom exception classes
│   ├── series.py                - Series class (1D arrays)
│   ├── frame.py                 - DataFrame class (2D tables)
│   ├── selection.py             - Indexing (loc, iloc, boolean)
│   ├── groupby.py               - GroupBy operations
│   ├── joins.py                 - Join/merge operations
│   ├── ioutils.py               - I/O (CSV, JSON, Markdown)
│   ├── window.py                - Window functions
│   ├── reshape.py               - Reshape operations
│   └── stats.py                 - Statistical functions
│
├── Test Files
│   ├── test_dataframe_series.py     - Series tests
│   ├── test_dataframe_frame.py      - DataFrame tests
│   ├── test_dataframe_groupby.py    - GroupBy tests
│   ├── test_dataframe_joins.py      - Join tests
│   ├── test_dataframe_io.py         - I/O tests
│   └── test_dataframe_window.py     - Window function tests
│
└── Documentation
    ├── README.md                - Comprehensive guide
    └── MANIFEST.md              - This file
```

## File Descriptions

### Core Library Files

#### `__init__.py` (84 lines)
- Public API exports
- Consolidated imports from all modules
- Version information
- Complete `__all__` export list

#### `_types.py` (169 lines)
- DType enumeration: INT, FLOAT, STRING, BOOL, DATETIME, NULL
- SortOrder, JoinType, AggFunc, IndexType enumerations
- ColumnInfo dataclass
- Helper functions: infer_dtype, promote_dtype, can_compare, default_value

#### `_exceptions.py` (64 lines)
- DataFrameError (base exception)
- ColumnNotFoundError (missing column)
- TypeMismatchError (type incompatibility)
- ShapeError (shape mismatch)
- MergeError (join/merge failure)

#### `series.py` (500 lines)
**Single-column typed data structure**

Core functionality:
- Element access and slicing with dtype conversion
- Null value handling (isna, fillna, dropna)
- Arithmetic operations (+, -, *, /, //, %, **)
- Comparison operations (==, !=, <, <=, >, >=)
- String methods (lower, upper, contains, replace, split)
- DateTime methods (year, month, day, hour)
- Aggregations (sum, mean, std, min, max, count, nunique)
- Value counts and frequency analysis
- Apply and map operations
- Type inference and conversion

#### `frame.py` (338 lines)
**Two-dimensional tabular data structure**

Core functionality:
- Construction from dict, list of dicts, with optional index
- Column access and manipulation (get, set, add, drop, rename)
- Row access and slicing (head, tail, sample)
- Information methods (shape, columns, dtypes, info, describe)
- Iteration (iterrows, itertuples)
- Conversion (to_dict, to_list, astype, copy, deepcopy)
- Display with aligned formatting
- Type conversion

#### `selection.py` (297 lines)
**Selection and indexing operations**

Classes:
- Loc: Label-based indexing (.loc[...])
- ILoc: Integer-based indexing (.iloc[...])
- QueryParser: Simple query string parsing

Features:
- Boolean mask indexing
- Multi-column selection
- Row and cell access
- Query string parsing with operators

#### `groupby.py` (270 lines)
**Grouped aggregation and transformation**

Operations:
- Group by single or multiple columns
- Aggregations: sum, mean, count, min, max, std, var, first, last
- Named aggregation with dict
- Transform (apply per group)
- Filter (groups matching predicate)
- Iteration over groups
- Group size statistics

#### `joins.py` (320 lines)
**Join/merge operations**

Join types:
- INNER: Only matching rows
- LEFT: All left + matching right
- RIGHT: All right + matching left
- OUTER: All rows
- CROSS: Cartesian product

Algorithms:
- Hash join (O(n+m))
- Sort-merge join (O(n log n + m log m))

Additional:
- concat: Vertical/horizontal concatenation
- cross_join: Cartesian product

#### `ioutils.py` (333 lines)
**Input/output operations**

CSV Operations:
- CSVReader: Parse CSV with type inference
- CSVWriter: Write CSV with options
- Handles: quoted fields, escaping, custom delimiters

JSON Operations:
- JSONHandler: Read/write JSON
- Supports: records, dict, index orientations

Other:
- MarkdownTable: Convert to Markdown format
- Type inference: Auto-detect INT, FLOAT, BOOL, STRING

#### `window.py` (346 lines)
**Window and rolling operations**

Rolling operations:
- rolling: Fixed-size windows
- expanding: Growing windows from start
- ewma: Exponentially weighted moving average

Ranking and shifting:
- rank: Multiple methods (average, first, dense, min, max)
- shift: Shift values forward/backward
- lag/lead: Previous/future values

Cumulative operations:
- cumsum: Cumulative sum
- cumprod: Cumulative product
- cummax: Cumulative maximum
- cummin: Cumulative minimum

DataFrame operations:
- rolling_apply: Apply to entire DataFrame

#### `reshape.py` (293 lines)
**Reshape and transform operations**

Operations:
- pivot: Long to wide conversion
- melt: Wide to long conversion
- stack/unstack: Row/column conversion
- transpose: Swap rows and columns
- crosstab: Frequency tables
- explode: List columns to rows

#### `stats.py` (329 lines)
**Statistical analysis**

Correlation & covariance:
- correlation: Pearson correlation matrix
- covariance: Covariance matrix

Quantiles:
- quantile: q-quantiles (0-1)
- percentile: p-percentiles (0-100)

Distribution:
- skewness: Third moment
- kurtosis: Excess kurtosis
- zscore: Standardized scores

Other:
- binning: Equal-width or equal-frequency
- value_frequency_analysis: Count, frequency, percentage

### Test Files

#### `test_dataframe_series.py` (356 lines)
**Series operations testing**

Test classes:
- TestSeriesConstruction: Initialization and dtype inference
- TestSeriesIndexing: Element access and slicing
- TestSeriesArithmetic: Arithmetic operations
- TestSeriesComparison: Comparison operations
- TestSeriesStringMethods: String operations
- TestSeriesNullHandling: Null value operations
- TestSeriesAggregations: Aggregation functions
- TestSeriesApply: Apply and map operations
- TestSeriesShape: Shape and properties
- TestSeriesErrors: Error handling

Total tests: 40+

#### `test_dataframe_frame.py` (280 lines)
**DataFrame operations testing**

Test classes:
- TestDataFrameConstruction: Initialization from various formats
- TestDataFrameColumnAccess: Column operations
- TestDataFrameInfo: Informational methods
- TestDataFrameSlicing: Head, tail, sample
- TestDataFrameIteration: iterrows, itertuples
- TestDataFrameCopy: Copy operations
- TestDataFrameConversion: to_dict, to_list, astype
- TestDataFrameDisplay: String representation
- TestDataFrameStatistics: describe method
- TestDataFrameErrors: Error handling

Total tests: 35+

#### `test_dataframe_groupby.py` (293 lines)
**GroupBy operations testing**

Test classes:
- TestGroupByConstruction: Initialization
- TestGroupByAggregation: All aggregation methods
- TestGroupByAggregate: aggregate method
- TestGroupByTransform: transform method
- TestGroupByFilter: filter method
- TestGroupByIteration: Iteration and get_group
- TestGroupBySize: size method
- TestGroupByMultipleColumns: Multi-column groupby
- TestGroupByEdgeCases: Null handling, single group

Total tests: 30+

#### `test_dataframe_joins.py` (265 lines)
**Join operations testing**

Test classes:
- TestInnerJoin: Inner join operations
- TestLeftJoin: Left join operations
- TestRightJoin: Right join operations
- TestOuterJoin: Outer join operations
- TestJoinOnMapping: Column mapping
- TestConcat: Concatenation operations
- TestCrossJoin: Cross join
- TestJoinErrors: Error handling
- TestJoinDataIntegrity: Data preservation
- TestJoinWithNulls: Null handling
- TestJoinPerformance: Large dataset joins

Total tests: 25+

#### `test_dataframe_io.py` (251 lines)
**I/O operations testing**

Test classes:
- TestCSVReading: CSV parsing
- TestCSVWriting: CSV output
- TestJSONReading: JSON parsing
- TestJSONWriting: JSON output
- TestMarkdownTable: Markdown output
- TestCSVRoundTrip: CSV write/read cycle
- TestJSONRoundTrip: JSON write/read cycle
- TestTypeInference: Type detection
- TestIOEdgeCases: Special cases

Total tests: 30+

#### `test_dataframe_window.py` (292 lines)
**Window function testing**

Test classes:
- TestRollingMean: Rolling mean operations
- TestRollingSum: Rolling sum
- TestRollingStd: Rolling std
- TestRollingMinMax: Rolling min/max
- TestRollingWithNulls: Null handling in rolling
- TestExpandingMean: Expanding windows
- TestExpandingSum: Expanding sum
- TestEWMA: Exponentially weighted moving average
- TestRank: Ranking operations
- TestShift: Shift operations
- TestLagLead: Lag and lead
- TestCumulative: Cumulative operations
- TestCumulativeWithNulls: Cumulative with nulls
- TestRollingApply: DataFrame rolling apply
- TestWindowErrors: Error handling
- TestWindowEdgeCases: Edge cases

Total tests: 45+

## Statistics Summary

### Code Organization

| Component | Files | Lines | Avg/Max |
|-----------|-------|-------|---------|
| Core Modules | 12 | 3,343 | 278/500 |
| Test Modules | 6 | 1,737 | 289/356 |
| Documentation | 2 | ~800 | - |
| **Total** | **20** | **~5,880** | - |

### Compliance

- ✓ All core modules: < 800 lines (max: 500)
- ✓ All test modules: < 400 lines (max: 356)
- ✓ Zero pandas dependency
- ✓ Full type annotations
- ✓ Comprehensive docstrings
- ✓ Real algorithm implementations
- ✓ 200+ test cases

### Feature Coverage

| Feature | Status | Lines |
|---------|--------|-------|
| Series (1D arrays) | ✓ | 500 |
| DataFrame (2D tables) | ✓ | 338 |
| Selection & indexing | ✓ | 297 |
| GroupBy operations | ✓ | 270 |
| Join/merge operations | ✓ | 320 |
| Window functions | ✓ | 346 |
| Reshape operations | ✓ | 293 |
| Statistical functions | ✓ | 329 |
| I/O operations | ✓ | 333 |
| Type system | ✓ | 169 |
| Exception handling | ✓ | 64 |

## Import Hierarchy

```
__init__.py
├── _types.py
├── _exceptions.py
├── series.py
│   ├── _types
│   └── _exceptions
├── frame.py
│   ├── _types
│   ├── _exceptions
│   └── series
├── selection.py
│   ├── _types
│   ├── _exceptions
│   ├── series
│   └── frame
├── groupby.py
│   ├── _types
│   ├── _exceptions
│   ├── series
│   └── frame
├── joins.py
│   ├── _types
│   ├── _exceptions
│   └── frame
├── ioutils.py
│   ├── _types
│   ├── _exceptions
│   ├── frame
│   └── series
├── window.py
│   ├── _types
│   ├── _exceptions
│   ├── series
│   └── frame
├── reshape.py
│   ├── _types
│   ├── _exceptions
│   ├── frame
│   └── series
└── stats.py
    ├── _types
    ├── _exceptions
    ├── frame
    └── series
```

## Getting Started

1. **Import the library**
   ```python
   from thomas.marketplace.dataframe import DataFrame, Series, GroupBy, JoinOperation
   ```

2. **Create data structures**
   ```python
   df = DataFrame({'a': [1, 2, 3], 'b': [4, 5, 6]})
   series = Series([1, 2, 3], name='my_series')
   ```

3. **Perform operations**
   ```python
   grouped = GroupBy(df, 'a').mean()
   subset = df[df['a'] > 1]
   ```

4. **Export data**
   ```python
   csv = CSVWriter.write_csv(df)
   json = JSONHandler.write_json(df, orient='records')
   ```

## Quality Metrics

- **Type Annotations**: 100% of public APIs
- **Docstrings**: Comprehensive for all classes and methods
- **Test Coverage**: 200+ test cases
- **Code Style**: PEP 8 compliant
- **Architecture**: Modular with clear separation of concerns
- **Performance**: Real algorithms with proper complexity analysis

## Development Notes

The library is designed to be:
- **Self-contained**: Zero external dependencies for core functionality
- **Extensible**: Easy to add new operations while maintaining structure
- **Efficient**: Uses appropriate data structures and algorithms
- **Educational**: Well-commented implementation of DataFrame concepts
- **Reliable**: Comprehensive error handling and validation

All modules maintain strict size constraints while providing complete functionality.
