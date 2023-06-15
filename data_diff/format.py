import collections
from typing import Any, Optional, List, Dict, Tuple

from runtype import dataclass
from data_diff.diff_tables import DiffResultWrapper


def jsonify(diff: DiffResultWrapper,
            dbt_model: str,
            with_summary: bool = False,
            with_columns: Optional[Dict[str, List[str]]] = None) -> 'JsonDiff':
    """
    Converts the diff result into a JSON-serializable format.
    Optionally add stats summary and schema diff.
    """
    diff_info = diff.info_tree.info
    table1 = diff_info.tables[0]
    table2 = diff_info.tables[1]
    key_columns = table1.key_columns

    t1_exclusive_rows = []
    t2_exclusive_rows = []
    diff_rows = []
    schema = [field for field, _ in diff_info.diff_schema]

    t1_exclusive_rows, t2_exclusive_rows, diff_rows = _group_rows(diff_info, schema)


    diff_rows_jsonified = []
    for row in diff_rows:
        diff_rows_jsonified.append(_jsonify_diff(row, key_columns))

    t1_exclusive_rows_jsonified = []
    for row in t1_exclusive_rows:
        t1_exclusive_rows_jsonified.append(_jsonify_exclusive(row, key_columns))

    t2_exclusive_rows_jsonified = []
    for row in t2_exclusive_rows:
        t2_exclusive_rows_jsonified.append(_jsonify_exclusive(row, key_columns))
    
    summary = None
    if with_summary:
        summary = _jsonify_diff_summary(diff.get_stats_dict())
    
    columns = None
    if with_columns:
        columns = _jsonify_columns_diff(with_columns)

    is_different = bool(
        t1_exclusive_rows
        or t2_exclusive_rows
        or diff_rows
        or with_columns and (
            with_columns['added']
            or with_columns['removed']
            or with_columns['changed']
        )
    )
    return JsonDiff(
        status="different" if is_different else "identical",
        model=dbt_model,
        table1=list(table1.table_path),
        table2=list(table2.table_path),
        rows=RowsDiff(
            exclusive=ExclusiveDiff(
                table1=t1_exclusive_rows_jsonified,
                table2=t2_exclusive_rows_jsonified
            ),
            diff=diff_rows_jsonified,
        ),
        summary=summary,
        columns=columns,
    ).json()



@dataclass
class JsonExclusiveRowValue:
    """
    Value of a single column in a row
    """
    isPK: bool
    value: Any


@dataclass
class JsonDiffRowValue:
    """
    Pair of diffed values for 2 rows with equal PKs
    """
    table1: Any
    table2: Any
    isDiff: bool
    isPK: bool


@dataclass
class Total:
    table1: int
    table2: int


@dataclass
class ExclusiveRows:
    table1: int
    table2: int


@dataclass
class Rows:
    total: Total
    exclusive: ExclusiveRows
    updated: int
    unchanged: int


@dataclass
class Stats:
    diffCounts: Dict[str, int]


@dataclass
class JsonDiffSummary:
    rows: Rows
    stats: Stats


@dataclass
class ExclusiveColumns:
    table1: List[str]
    table2: List[str]


@dataclass
class JsonColumnsSummary:
    exclusive: ExclusiveColumns
    typeChanged: List[str]


@dataclass
class ExclusiveDiff:
    table1: List[Dict[str, JsonExclusiveRowValue]]
    table2: List[Dict[str, JsonExclusiveRowValue]]


@dataclass
class RowsDiff:
    exclusive: ExclusiveDiff
    diff: List[Dict[str, JsonDiffRowValue]]


@dataclass
class JsonDiff:
    status: str # Literal ["identical", "different"]
    model: str
    table1: List[str]
    table2: List[str]
    rows: RowsDiff
    summary: Optional[JsonDiffSummary]
    columns: Optional[JsonColumnsSummary]

    version: str = '1.0.0'


def _group_rows(diff_info: DiffResultWrapper, 
                schema: List[str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    t1_exclusive_rows = []
    t2_exclusive_rows = []
    diff_rows = []

    for row in diff_info.diff:
        row_w_schema = dict(zip(schema, row))
        is_t1_exclusive = row_w_schema['is_exclusive_a']
        is_t2_exclusive = row_w_schema['is_exclusive_b']

        if is_t1_exclusive:
            t1_exclusive_rows.append(row_w_schema)

        elif is_t2_exclusive:
            t2_exclusive_rows.append(row_w_schema)

        else:
            diff_rows.append(row_w_schema)
    
    return t1_exclusive_rows, t2_exclusive_rows, diff_rows


def _jsonify_diff(row: Dict[str, Any], key_columns: List[str]) -> Dict[str, JsonDiffRowValue]:
    columns = collections.defaultdict(dict)
    for field, value in row.items():
        if field in ('is_exclusive_a', 'is_exclusive_b'):
            continue

        if field.startswith('is_diff_'):
            column_name = field.replace('is_diff_', '')
            columns[column_name]['isDiff'] = bool(value)

        elif field.endswith('_a'):
            column_name = field.replace('_a', '')
            columns[column_name]['table1'] = value
            columns[column_name]['isPK'] = column_name in key_columns

        elif field.endswith('_b'):
            column_name = field.replace('_b', '')
            columns[column_name]['table2'] = value
            columns[column_name]['isPK'] = column_name in key_columns
    
    return {
        column: JsonDiffRowValue(**data)
        for column, data in columns.items()
    }


def _jsonify_exclusive(row: Dict[str, Any], key_columns: List[str]) -> Dict[str, JsonExclusiveRowValue]:
    columns = collections.defaultdict(dict)
    for field, value in row.items():
        if field in ('is_exclusive_a', 'is_exclusive_b'):
            continue
        if field.startswith('is_diff_'):
            continue
        if field.endswith('_b') and row['is_exclusive_b']:
            column_name = field.replace('_b', '')
            columns[column_name]['isPK'] = column_name in key_columns
            columns[column_name]['value'] = value
        elif field.endswith('_a') and row['is_exclusive_a']:
            column_name = field.replace('_a', '')
            columns[column_name]['isPK'] = column_name in key_columns
            columns[column_name]['value'] = value
    return {
        column: JsonExclusiveRowValue(**data)
        for column, data in columns.items()
    }


def _jsonify_diff_summary(stats_dict: dict) -> JsonDiffSummary:
    return JsonDiffSummary(
        rows=Rows(
            total=Total(
                table1=stats_dict["rows_A"],
                table2=stats_dict["rows_B"]
            ),
            exclusive=ExclusiveRows(
                table1=stats_dict["exclusive_A"],
                table2=stats_dict["exclusive_B"],
            ),
            updated=stats_dict["updated"],
            unchanged=stats_dict["unchanged"]
        ),
        stats=Stats(
            diffCounts=stats_dict["stats"]['diff_counts']
        )
    )


def _jsonify_columns_diff(columns_diff: Dict[str, List[str]]) -> JsonColumnsSummary:
    return JsonColumnsSummary(
        exclusive= ExclusiveColumns(
            table2= list(columns_diff.get('added', [])),
            table1= list(columns_diff.get('removed', [])),
        ),
        typeChanged=list(columns_diff.get('changed', [])),
    )