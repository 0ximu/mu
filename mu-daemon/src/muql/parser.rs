//! MUQL parser - converts query strings to AST.

use pest::Parser;
use pest_derive::Parser;
use thiserror::Error;

#[derive(Parser)]
#[grammar = "muql/grammar.pest"]
pub struct MUQLParser;

/// Parse error for MUQL queries.
#[derive(Debug, Error)]
pub enum ParseError {
    #[error("Syntax error: {0}")]
    Syntax(String),
    #[error("Unexpected token at position {position}: {message}")]
    UnexpectedToken { position: usize, message: String },
}

/// Parsed MUQL query.
#[derive(Debug, Clone)]
pub enum Query {
    Select(SelectQuery),
    Show(ShowQuery),
    Find(FindQuery),
    FindCycles(FindCyclesQuery),
    Path(PathQuery),
    Analyze(AnalyzeQuery),
    Describe(DescribeQuery),
}

#[derive(Debug, Clone)]
pub struct SelectQuery {
    pub fields: Vec<SelectField>,
    pub node_type: NodeTypeFilter,
    pub where_clause: Option<Condition>,
    pub group_by: Vec<String>,
    pub having_clause: Option<Condition>,
    pub order_by: Vec<OrderField>,
    pub limit: Option<usize>,
}

#[derive(Debug, Clone)]
pub struct SelectField {
    pub name: String,
    pub aggregate: Option<AggregateFunc>,
    pub alias: Option<String>,
    pub is_star: bool,
}

#[derive(Debug, Clone, Copy)]
pub enum AggregateFunc {
    Count,
    Avg,
    Max,
    Min,
    Sum,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum NodeTypeFilter {
    Functions,
    Classes,
    Modules,
    Nodes,
    Methods,
}

impl NodeTypeFilter {
    pub fn to_sql_type(&self) -> &'static str {
        match self {
            NodeTypeFilter::Functions => "function",
            NodeTypeFilter::Classes => "class",
            NodeTypeFilter::Modules => "module",
            NodeTypeFilter::Nodes => "%", // All types
            NodeTypeFilter::Methods => "function", // Methods are functions
        }
    }
}

#[derive(Debug, Clone)]
pub struct Condition {
    pub comparisons: Vec<Comparison>,
    pub operator: LogicalOp,
}

#[derive(Debug, Clone, Copy)]
pub enum LogicalOp {
    And,
    Or,
}

#[derive(Debug, Clone)]
pub struct Comparison {
    pub field: String,
    pub op: ComparisonOp,
    pub value: Value,
}

#[derive(Debug, Clone, Copy)]
pub enum ComparisonOp {
    Eq,
    Ne,
    Gt,
    Lt,
    Gte,
    Lte,
    Like,
    In,
    NotIn,
}

#[derive(Debug, Clone)]
pub enum Value {
    String(String),
    Number(i64),
    Bool(bool),
    Null,
    List(Vec<Value>),
}

#[derive(Debug, Clone)]
pub struct OrderField {
    pub name: String,
    pub descending: bool,
}

#[derive(Debug, Clone)]
pub struct ShowQuery {
    pub show_type: ShowType,
    pub target: String,
    pub depth: usize,
}

#[derive(Debug, Clone, Copy)]
pub enum ShowType {
    Dependencies,
    Dependents,
    Callers,
    Callees,
    Inheritance,
    Implementations,
    Children,
    Parents,
    Impact,
    Ancestors,
}

#[derive(Debug, Clone)]
pub struct FindQuery {
    pub node_type: NodeTypeFilter,
    pub condition: FindCondition,
}

#[derive(Debug, Clone)]
pub enum FindCondition {
    Calling(String),
    CalledBy(String),
    Importing(String),
    ImportedBy(String),
    Inheriting(String),
    Implementing(String),
    WithDecorator(String),
    WithAnnotation(String),
    Matching(String),
    SimilarTo(String),
}

#[derive(Debug, Clone)]
pub struct FindCyclesQuery {
    pub edge_types: Option<Vec<String>>,
}

#[derive(Debug, Clone)]
pub struct PathQuery {
    pub from_node: String,
    pub to_node: String,
    pub max_depth: usize,
    pub via_edge: Option<String>,
}

#[derive(Debug, Clone)]
pub struct AnalyzeQuery {
    pub analysis_type: AnalysisType,
    pub target: Option<String>,
}

#[derive(Debug, Clone, Copy)]
pub enum AnalysisType {
    Coupling,
    Cohesion,
    Complexity,
    Hotspots,
    Circular,
    Unused,
    Impact,
}

#[derive(Debug, Clone)]
pub struct DescribeQuery {
    pub target: DescribeTarget,
}

#[derive(Debug, Clone)]
pub enum DescribeTarget {
    Tables,
    Columns(NodeTypeFilter),
    NodeType(NodeTypeFilter),
}

/// Parse a MUQL query string into an AST.
pub fn parse(input: &str) -> Result<Query, ParseError> {
    let pairs = MUQLParser::parse(Rule::query, input)
        .map_err(|e| ParseError::Syntax(e.to_string()))?;

    let query_pair = pairs
        .into_iter()
        .next()
        .ok_or_else(|| ParseError::Syntax("Empty query".to_string()))?;

    parse_query(query_pair)
}

fn parse_query(pair: pest::iterators::Pair<Rule>) -> Result<Query, ParseError> {
    let inner = pair.into_inner().next()
        .ok_or_else(|| ParseError::Syntax("Empty query".to_string()))?;

    let statement = inner.into_inner().next()
        .ok_or_else(|| ParseError::Syntax("No statement found".to_string()))?;

    match statement.as_rule() {
        Rule::select_query => Ok(Query::Select(parse_select_query(statement)?)),
        Rule::show_query => Ok(Query::Show(parse_show_query(statement)?)),
        Rule::show_tables_query => Ok(Query::Describe(DescribeQuery {
            target: DescribeTarget::Tables,
        })),
        Rule::show_columns_query => Ok(Query::Describe(parse_show_columns_query(statement)?)),
        Rule::find_query => Ok(Query::Find(parse_find_query(statement)?)),
        Rule::find_cycles_query => Ok(Query::FindCycles(parse_find_cycles_query(statement)?)),
        Rule::path_query => Ok(Query::Path(parse_path_query(statement)?)),
        Rule::analyze_query => Ok(Query::Analyze(parse_analyze_query(statement)?)),
        Rule::describe_query => Ok(Query::Describe(parse_describe_query(statement)?)),
        _ => Err(ParseError::Syntax(format!("Unknown query type: {:?}", statement.as_rule()))),
    }
}

fn parse_select_query(pair: pest::iterators::Pair<Rule>) -> Result<SelectQuery, ParseError> {
    let mut fields = Vec::new();
    let mut node_type = NodeTypeFilter::Nodes;
    let mut where_clause = None;
    let mut group_by = Vec::new();
    let mut having_clause = None;
    let mut order_by = Vec::new();
    let mut limit = None;

    for inner in pair.into_inner() {
        match inner.as_rule() {
            Rule::select_list => {
                fields = parse_select_list(inner)?;
            }
            Rule::node_type => {
                node_type = parse_node_type(inner)?;
            }
            Rule::where_clause => {
                where_clause = Some(parse_where_clause(inner)?);
            }
            Rule::group_by_clause => {
                group_by = parse_group_by_clause(inner)?;
            }
            Rule::having_clause => {
                having_clause = Some(parse_having_clause(inner)?);
            }
            Rule::order_clause => {
                order_by = parse_order_clause(inner)?;
            }
            Rule::limit_clause => {
                limit = Some(parse_limit_clause(inner)?);
            }
            _ => {}
        }
    }

    Ok(SelectQuery {
        fields,
        node_type,
        where_clause,
        group_by,
        having_clause,
        order_by,
        limit,
    })
}

fn parse_select_list(pair: pest::iterators::Pair<Rule>) -> Result<Vec<SelectField>, ParseError> {
    let mut fields = Vec::new();

    for inner in pair.into_inner() {
        match inner.as_rule() {
            Rule::STAR => {
                fields.push(SelectField {
                    name: "*".to_string(),
                    aggregate: None,
                    alias: None,
                    is_star: true,
                });
            }
            Rule::field_list => {
                for field_pair in inner.into_inner() {
                    fields.push(parse_field(field_pair)?);
                }
            }
            _ => {}
        }
    }

    Ok(fields)
}

fn parse_field(pair: pest::iterators::Pair<Rule>) -> Result<SelectField, ParseError> {
    let mut agg = None;
    let mut name = String::new();
    let mut alias = None;
    let mut is_star = false;

    for inner in pair.into_inner() {
        match inner.as_rule() {
            Rule::aggregate_fn => {
                for part in inner.into_inner() {
                    match part.as_rule() {
                        Rule::COUNT => agg = Some(AggregateFunc::Count),
                        Rule::AVG => agg = Some(AggregateFunc::Avg),
                        Rule::MAX => agg = Some(AggregateFunc::Max),
                        Rule::MIN => agg = Some(AggregateFunc::Min),
                        Rule::SUM => agg = Some(AggregateFunc::Sum),
                        Rule::STAR => {
                            name = "*".to_string();
                            is_star = true;
                        }
                        Rule::identifier => name = part.as_str().to_string(),
                        _ => {}
                    }
                }
            }
            Rule::identifier => {
                name = inner.as_str().to_string();
            }
            Rule::alias_clause => {
                for part in inner.into_inner() {
                    if part.as_rule() == Rule::identifier {
                        alias = Some(part.as_str().to_string());
                    }
                }
            }
            _ => {}
        }
    }

    if name.is_empty() {
        return Err(ParseError::Syntax("Empty field".to_string()));
    }

    Ok(SelectField {
        name,
        aggregate: agg,
        alias,
        is_star,
    })
}

fn parse_node_type(pair: pest::iterators::Pair<Rule>) -> Result<NodeTypeFilter, ParseError> {
    let inner = pair.into_inner().next()
        .ok_or_else(|| ParseError::Syntax("Empty node type".to_string()))?;

    match inner.as_rule() {
        Rule::FUNCTIONS => Ok(NodeTypeFilter::Functions),
        Rule::CLASSES => Ok(NodeTypeFilter::Classes),
        Rule::MODULES => Ok(NodeTypeFilter::Modules),
        Rule::NODES => Ok(NodeTypeFilter::Nodes),
        Rule::METHODS => Ok(NodeTypeFilter::Methods),
        _ => Err(ParseError::Syntax(format!("Unknown node type: {:?}", inner.as_rule()))),
    }
}

fn parse_where_clause(pair: pest::iterators::Pair<Rule>) -> Result<Condition, ParseError> {
    let inner = pair.into_inner().next()
        .ok_or_else(|| ParseError::Syntax("Empty where clause".to_string()))?;

    parse_condition(inner)
}

fn parse_condition(pair: pest::iterators::Pair<Rule>) -> Result<Condition, ParseError> {
    // Simplified: just collect all comparisons with AND
    let mut comparisons = Vec::new();

    fn extract_comparisons(pair: pest::iterators::Pair<Rule>, comparisons: &mut Vec<Comparison>) -> Result<(), ParseError> {
        match pair.as_rule() {
            Rule::comparison => {
                comparisons.push(parse_comparison(pair)?);
            }
            Rule::condition | Rule::or_condition | Rule::and_condition => {
                for inner in pair.into_inner() {
                    extract_comparisons(inner, comparisons)?;
                }
            }
            _ => {}
        }
        Ok(())
    }

    extract_comparisons(pair, &mut comparisons)?;

    Ok(Condition {
        comparisons,
        operator: LogicalOp::And,
    })
}

fn parse_comparison(pair: pest::iterators::Pair<Rule>) -> Result<Comparison, ParseError> {
    let mut field = String::new();
    let mut op = ComparisonOp::Eq;
    let mut value = Value::Null;

    for inner in pair.into_inner() {
        match inner.as_rule() {
            Rule::identifier => field = inner.as_str().to_string(),
            Rule::aggregate_fn => {
                // Handle aggregate functions in comparisons (for HAVING clause)
                let mut agg_name = String::new();
                let mut agg_field = String::new();

                for part in inner.into_inner() {
                    match part.as_rule() {
                        Rule::COUNT => agg_name = "COUNT".to_string(),
                        Rule::AVG => agg_name = "AVG".to_string(),
                        Rule::MAX => agg_name = "MAX".to_string(),
                        Rule::MIN => agg_name = "MIN".to_string(),
                        Rule::SUM => agg_name = "SUM".to_string(),
                        Rule::STAR => agg_field = "*".to_string(),
                        Rule::identifier => agg_field = part.as_str().to_string(),
                        _ => {}
                    }
                }
                field = format!("{}({})", agg_name, agg_field);
            }
            Rule::comparison_op => {
                op = match inner.as_str() {
                    "=" => ComparisonOp::Eq,
                    "!=" | "<>" => ComparisonOp::Ne,
                    ">" => ComparisonOp::Gt,
                    "<" => ComparisonOp::Lt,
                    ">=" => ComparisonOp::Gte,
                    "<=" => ComparisonOp::Lte,
                    _ => ComparisonOp::Eq,
                };
            }
            Rule::LIKE => op = ComparisonOp::Like,
            Rule::IN => op = ComparisonOp::In,
            Rule::NOT => {
                // Will be followed by IN
            }
            Rule::value => {
                value = parse_value(inner)?;
            }
            Rule::value_list => {
                let values: Vec<Value> = inner
                    .into_inner()
                    .filter_map(|v| parse_value(v).ok())
                    .collect();
                value = Value::List(values);
            }
            Rule::condition => {
                // Nested condition - for now just skip
            }
            _ => {}
        }
    }

    Ok(Comparison { field, op, value })
}

fn parse_value(pair: pest::iterators::Pair<Rule>) -> Result<Value, ParseError> {
    let inner = pair.into_inner().next()
        .ok_or_else(|| ParseError::Syntax("Empty value".to_string()))?;

    match inner.as_rule() {
        Rule::string_value => {
            let s = inner.as_str();
            // Remove quotes
            let s = &s[1..s.len()-1];
            Ok(Value::String(s.to_string()))
        }
        Rule::number_value => {
            let n: i64 = inner.as_str().parse()
                .map_err(|_| ParseError::Syntax("Invalid number".to_string()))?;
            Ok(Value::Number(n))
        }
        Rule::TRUE => Ok(Value::Bool(true)),
        Rule::FALSE => Ok(Value::Bool(false)),
        Rule::NULL => Ok(Value::Null),
        _ => Err(ParseError::Syntax(format!("Unknown value type: {:?}", inner.as_rule()))),
    }
}

fn parse_order_clause(pair: pest::iterators::Pair<Rule>) -> Result<Vec<OrderField>, ParseError> {
    let mut fields = Vec::new();

    for inner in pair.into_inner() {
        if inner.as_rule() == Rule::order_field {
            let mut name = String::new();
            let mut descending = false;

            for part in inner.into_inner() {
                match part.as_rule() {
                    Rule::identifier => name = part.as_str().to_string(),
                    Rule::ASC => descending = false,
                    Rule::DESC => descending = true,
                    _ => {}
                }
            }

            fields.push(OrderField { name, descending });
        }
    }

    Ok(fields)
}

fn parse_limit_clause(pair: pest::iterators::Pair<Rule>) -> Result<usize, ParseError> {
    for inner in pair.into_inner() {
        if inner.as_rule() == Rule::number_value {
            return inner.as_str().parse()
                .map_err(|_| ParseError::Syntax("Invalid limit".to_string()));
        }
    }
    Ok(100) // Default
}

fn parse_group_by_clause(pair: pest::iterators::Pair<Rule>) -> Result<Vec<String>, ParseError> {
    let mut fields = Vec::new();

    for inner in pair.into_inner() {
        if inner.as_rule() == Rule::group_field {
            for part in inner.into_inner() {
                if part.as_rule() == Rule::identifier {
                    fields.push(part.as_str().to_string());
                }
            }
        }
    }

    Ok(fields)
}

fn parse_having_clause(pair: pest::iterators::Pair<Rule>) -> Result<Condition, ParseError> {
    let inner = pair.into_inner().next()
        .ok_or_else(|| ParseError::Syntax("Empty having clause".to_string()))?;

    parse_condition(inner)
}

fn parse_show_query(pair: pest::iterators::Pair<Rule>) -> Result<ShowQuery, ParseError> {
    let mut show_type = ShowType::Dependencies;
    let mut target = String::new();
    let mut depth = 1;

    for inner in pair.into_inner() {
        match inner.as_rule() {
            Rule::show_type => {
                let type_inner = inner.into_inner().next()
                    .ok_or_else(|| ParseError::Syntax("Empty show type".to_string()))?;
                show_type = match type_inner.as_rule() {
                    Rule::DEPENDENCIES => ShowType::Dependencies,
                    Rule::DEPENDENTS => ShowType::Dependents,
                    Rule::CALLERS => ShowType::Callers,
                    Rule::CALLEES => ShowType::Callees,
                    Rule::INHERITANCE => ShowType::Inheritance,
                    Rule::IMPLEMENTATIONS => ShowType::Implementations,
                    Rule::CHILDREN => ShowType::Children,
                    Rule::PARENTS => ShowType::Parents,
                    Rule::IMPACT => ShowType::Impact,
                    Rule::ANCESTORS => ShowType::Ancestors,
                    _ => ShowType::Dependencies,
                };
            }
            Rule::node_ref => {
                target = parse_node_ref(inner)?;
            }
            Rule::depth_clause => {
                for d in inner.into_inner() {
                    if d.as_rule() == Rule::number_value {
                        depth = d.as_str().parse().unwrap_or(1);
                    }
                }
            }
            _ => {}
        }
    }

    Ok(ShowQuery {
        show_type,
        target,
        depth,
    })
}

fn parse_node_ref(pair: pest::iterators::Pair<Rule>) -> Result<String, ParseError> {
    let inner = pair.into_inner().next()
        .ok_or_else(|| ParseError::Syntax("Empty node ref".to_string()))?;

    match inner.as_rule() {
        Rule::string_value => {
            let s = inner.as_str();
            Ok(s[1..s.len()-1].to_string())
        }
        Rule::qualified_name | Rule::identifier => {
            Ok(inner.as_str().to_string())
        }
        _ => Err(ParseError::Syntax(format!("Unknown node ref type: {:?}", inner.as_rule()))),
    }
}

fn parse_find_query(pair: pest::iterators::Pair<Rule>) -> Result<FindQuery, ParseError> {
    let mut node_type = NodeTypeFilter::Functions;
    let mut condition = FindCondition::Matching("*".to_string());

    for inner in pair.into_inner() {
        match inner.as_rule() {
            Rule::find_node_type => {
                let type_inner = inner.into_inner().next()
                    .ok_or_else(|| ParseError::Syntax("Empty find node type".to_string()))?;
                node_type = match type_inner.as_rule() {
                    Rule::FUNCTIONS => NodeTypeFilter::Functions,
                    Rule::CLASSES => NodeTypeFilter::Classes,
                    Rule::MODULES => NodeTypeFilter::Modules,
                    Rule::METHODS => NodeTypeFilter::Methods,
                    _ => NodeTypeFilter::Functions,
                };
            }
            Rule::find_condition => {
                condition = parse_find_condition(inner)?;
            }
            _ => {}
        }
    }

    Ok(FindQuery { node_type, condition })
}

fn parse_find_condition(pair: pest::iterators::Pair<Rule>) -> Result<FindCondition, ParseError> {
    let mut condition_type: Option<&str> = None;
    let mut target = String::new();

    for inner in pair.into_inner() {
        match inner.as_rule() {
            Rule::CALLING => condition_type = Some("calling"),
            Rule::CALLED => condition_type = Some("called_by"),
            Rule::IMPORTING => condition_type = Some("importing"),
            Rule::IMPORTED => condition_type = Some("imported_by"),
            Rule::INHERITING => condition_type = Some("inheriting"),
            Rule::IMPLEMENTING => condition_type = Some("implementing"),
            Rule::DECORATOR => condition_type = Some("decorator"),
            Rule::ANNOTATION => condition_type = Some("annotation"),
            Rule::MATCHING => condition_type = Some("matching"),
            Rule::SIMILAR => condition_type = Some("similar"),
            Rule::node_ref => target = parse_node_ref(inner)?,
            Rule::string_value => {
                let s = inner.as_str();
                target = s[1..s.len()-1].to_string();
            }
            _ => {}
        }
    }

    Ok(match condition_type {
        Some("calling") => FindCondition::Calling(target),
        Some("called_by") => FindCondition::CalledBy(target),
        Some("importing") => FindCondition::Importing(target),
        Some("imported_by") => FindCondition::ImportedBy(target),
        Some("inheriting") => FindCondition::Inheriting(target),
        Some("implementing") => FindCondition::Implementing(target),
        Some("decorator") => FindCondition::WithDecorator(target),
        Some("annotation") => FindCondition::WithAnnotation(target),
        Some("matching") => FindCondition::Matching(target),
        Some("similar") => FindCondition::SimilarTo(target),
        _ => FindCondition::Matching(target),
    })
}

fn parse_find_cycles_query(pair: pest::iterators::Pair<Rule>) -> Result<FindCyclesQuery, ParseError> {
    let mut edge_types = None;

    for inner in pair.into_inner() {
        if inner.as_rule() == Rule::edge_type_filter {
            let mut types = Vec::new();
            for part in inner.into_inner() {
                if part.as_rule() == Rule::string_value {
                    let s = part.as_str();
                    types.push(s[1..s.len()-1].to_string());
                } else if part.as_rule() == Rule::string_list {
                    for sv in part.into_inner() {
                        let s = sv.as_str();
                        types.push(s[1..s.len()-1].to_string());
                    }
                }
            }
            if !types.is_empty() {
                edge_types = Some(types);
            }
        }
    }

    Ok(FindCyclesQuery { edge_types })
}

fn parse_path_query(pair: pest::iterators::Pair<Rule>) -> Result<PathQuery, ParseError> {
    let mut from_node = String::new();
    let mut to_node = String::new();
    let mut max_depth = 10;
    let mut via_edge = None;
    let mut node_refs = Vec::new();

    for inner in pair.into_inner() {
        match inner.as_rule() {
            Rule::node_ref => {
                node_refs.push(parse_node_ref(inner)?);
            }
            Rule::max_depth_clause => {
                for d in inner.into_inner() {
                    if d.as_rule() == Rule::number_value {
                        max_depth = d.as_str().parse().unwrap_or(10);
                    }
                }
            }
            Rule::via_clause => {
                for e in inner.into_inner() {
                    if e.as_rule() == Rule::edge_type {
                        via_edge = Some(e.as_str().to_lowercase());
                    }
                }
            }
            _ => {}
        }
    }

    if node_refs.len() >= 2 {
        from_node = node_refs[0].clone();
        to_node = node_refs[1].clone();
    }

    Ok(PathQuery {
        from_node,
        to_node,
        max_depth,
        via_edge,
    })
}

fn parse_analyze_query(pair: pest::iterators::Pair<Rule>) -> Result<AnalyzeQuery, ParseError> {
    let mut analysis_type = AnalysisType::Complexity;
    let mut target = None;

    for inner in pair.into_inner() {
        match inner.as_rule() {
            Rule::analysis_type => {
                let type_inner = inner.into_inner().next()
                    .ok_or_else(|| ParseError::Syntax("Empty analysis type".to_string()))?;
                analysis_type = match type_inner.as_rule() {
                    Rule::COUPLING => AnalysisType::Coupling,
                    Rule::COHESION => AnalysisType::Cohesion,
                    Rule::COMPLEXITY => AnalysisType::Complexity,
                    Rule::HOTSPOTS => AnalysisType::Hotspots,
                    Rule::CIRCULAR => AnalysisType::Circular,
                    Rule::UNUSED => AnalysisType::Unused,
                    Rule::IMPACT_KW => AnalysisType::Impact,
                    _ => AnalysisType::Complexity,
                };
            }
            Rule::for_clause => {
                for f in inner.into_inner() {
                    if f.as_rule() == Rule::node_ref {
                        target = Some(parse_node_ref(f)?);
                    }
                }
            }
            _ => {}
        }
    }

    Ok(AnalyzeQuery {
        analysis_type,
        target,
    })
}

fn parse_describe_query(pair: pest::iterators::Pair<Rule>) -> Result<DescribeQuery, ParseError> {
    let mut target = DescribeTarget::Tables;

    for inner in pair.into_inner() {
        if inner.as_rule() == Rule::describe_target {
            for part in inner.into_inner() {
                match part.as_rule() {
                    Rule::TABLES => target = DescribeTarget::Tables,
                    Rule::COLUMNS => {
                        // Next should be node_type
                    }
                    Rule::node_type => {
                        let nt = parse_node_type(part)?;
                        target = DescribeTarget::NodeType(nt);
                    }
                    _ => {}
                }
            }
        }
    }

    Ok(DescribeQuery { target })
}

fn parse_show_columns_query(pair: pest::iterators::Pair<Rule>) -> Result<DescribeQuery, ParseError> {
    // SHOW COLUMNS FROM <node_type> -> DescribeQuery with Columns target
    for inner in pair.into_inner() {
        if inner.as_rule() == Rule::node_type {
            let nt = parse_node_type(inner)?;
            return Ok(DescribeQuery {
                target: DescribeTarget::Columns(nt),
            });
        }
    }

    // Fallback to Tables if no node_type found (shouldn't happen with valid grammar)
    Ok(DescribeQuery {
        target: DescribeTarget::Tables,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_select_all() {
        let q = parse("SELECT * FROM functions").unwrap();
        match q {
            Query::Select(s) => {
                assert!(s.fields[0].is_star);
                assert_eq!(s.node_type, NodeTypeFilter::Functions);
            }
            _ => panic!("Expected Select query"),
        }
    }

    #[test]
    fn test_parse_select_with_where() {
        let q = parse("SELECT name FROM functions WHERE complexity > 10").unwrap();
        match q {
            Query::Select(s) => {
                assert_eq!(s.fields[0].name, "name");
                assert!(s.where_clause.is_some());
            }
            _ => panic!("Expected Select query"),
        }
    }

    #[test]
    fn test_parse_show() {
        let q = parse("SHOW dependencies OF MUbase DEPTH 3").unwrap();
        match q {
            Query::Show(s) => {
                assert!(matches!(s.show_type, ShowType::Dependencies));
                assert_eq!(s.target, "MUbase");
                assert_eq!(s.depth, 3);
            }
            _ => panic!("Expected Show query"),
        }
    }

    #[test]
    fn test_parse_find_cycles() {
        let q = parse("FIND CYCLES").unwrap();
        match q {
            Query::FindCycles(f) => {
                assert!(f.edge_types.is_none());
            }
            _ => panic!("Expected FindCycles query"),
        }
    }

    #[test]
    fn test_parse_group_by() {
        let q = parse("SELECT type, COUNT(*) FROM nodes GROUP BY type").unwrap();
        match q {
            Query::Select(s) => {
                assert_eq!(s.fields.len(), 2);
                assert_eq!(s.fields[0].name, "type");
                assert!(s.fields[1].aggregate.is_some());
                assert_eq!(s.group_by.len(), 1);
                assert_eq!(s.group_by[0], "type");
            }
            _ => panic!("Expected Select query"),
        }
    }

    #[test]
    fn test_parse_group_by_multiple() {
        let q = parse("SELECT file_path, type, COUNT(*) FROM functions GROUP BY file_path, type").unwrap();
        match q {
            Query::Select(s) => {
                assert_eq!(s.group_by.len(), 2);
                assert_eq!(s.group_by[0], "file_path");
                assert_eq!(s.group_by[1], "type");
            }
            _ => panic!("Expected Select query"),
        }
    }

    #[test]
    fn test_parse_having() {
        let q = parse("SELECT type, COUNT(*) FROM nodes GROUP BY type HAVING COUNT(*) > 10").unwrap();
        match q {
            Query::Select(s) => {
                assert!(!s.group_by.is_empty());
                assert!(s.having_clause.is_some());
                let having = s.having_clause.unwrap();
                assert_eq!(having.comparisons.len(), 1);
            }
            _ => panic!("Expected Select query"),
        }
    }

    #[test]
    fn test_parse_alias() {
        let q = parse("SELECT name AS function_name FROM functions").unwrap();
        match q {
            Query::Select(s) => {
                assert_eq!(s.fields[0].name, "name");
                assert_eq!(s.fields[0].alias, Some("function_name".to_string()));
            }
            _ => panic!("Expected Select query"),
        }
    }

    #[test]
    fn test_parse_aggregate_alias() {
        let q = parse("SELECT COUNT(*) AS total FROM classes").unwrap();
        match q {
            Query::Select(s) => {
                assert!(s.fields[0].aggregate.is_some());
                assert_eq!(s.fields[0].alias, Some("total".to_string()));
            }
            _ => panic!("Expected Select query"),
        }
    }

    #[test]
    fn test_parse_complex_query() {
        let q = parse("SELECT file_path, AVG(complexity) AS avg_complexity FROM functions WHERE complexity > 5 GROUP BY file_path HAVING AVG(complexity) > 10 ORDER BY avg_complexity DESC LIMIT 20").unwrap();
        match q {
            Query::Select(s) => {
                assert_eq!(s.fields.len(), 2);
                assert_eq!(s.fields[1].alias, Some("avg_complexity".to_string()));
                assert!(s.where_clause.is_some());
                assert_eq!(s.group_by.len(), 1);
                assert!(s.having_clause.is_some());
                assert_eq!(s.order_by.len(), 1);
                assert!(s.order_by[0].descending);
                assert_eq!(s.limit, Some(20));
            }
            _ => panic!("Expected Select query"),
        }
    }

    #[test]
    fn test_parse_show_tables() {
        let q = parse("SHOW TABLES").unwrap();
        match q {
            Query::Describe(d) => {
                assert!(matches!(d.target, DescribeTarget::Tables));
            }
            _ => panic!("Expected Describe query"),
        }
    }

    #[test]
    fn test_parse_show_columns() {
        let q = parse("SHOW COLUMNS FROM functions").unwrap();
        match q {
            Query::Describe(d) => {
                match d.target {
                    DescribeTarget::Columns(nt) => {
                        assert_eq!(nt, NodeTypeFilter::Functions);
                    }
                    _ => panic!("Expected Columns target"),
                }
            }
            _ => panic!("Expected Describe query"),
        }
    }

    #[test]
    fn test_parse_show_columns_classes() {
        let q = parse("SHOW COLUMNS FROM classes").unwrap();
        match q {
            Query::Describe(d) => {
                match d.target {
                    DescribeTarget::Columns(nt) => {
                        assert_eq!(nt, NodeTypeFilter::Classes);
                    }
                    _ => panic!("Expected Columns target"),
                }
            }
            _ => panic!("Expected Describe query"),
        }
    }
}
