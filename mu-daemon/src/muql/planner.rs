//! MUQL query planner - converts AST to execution plan.

use super::parser::*;

/// Execution plan for a MUQL query.
#[derive(Debug)]
pub enum ExecutionPlan {
    /// Direct SQL query against DuckDB
    Sql(String),
    /// Graph traversal operation
    Graph(GraphOperation),
    /// Analysis operation
    Analysis(AnalysisOperation),
    /// Schema introspection
    Schema(SchemaOperation),
}

/// Graph traversal operations.
#[derive(Debug)]
pub struct GraphOperation {
    pub op_type: GraphOpType,
    pub target: String,
    pub depth: usize,
    pub edge_types: Option<Vec<String>>,
}

#[derive(Debug)]
pub enum GraphOpType {
    Dependencies,
    Dependents,
    Impact,
    Ancestors,
    Children,
    Path { to: String, via: Option<String> },
    Cycles,
}

/// Analysis operations.
#[derive(Debug)]
pub struct AnalysisOperation {
    pub analysis_type: AnalysisType,
    pub target: Option<String>,
}

/// Schema introspection operations.
#[derive(Debug)]
pub enum SchemaOperation {
    ListTables,
    ListColumns(NodeTypeFilter),
    DescribeNodeType(NodeTypeFilter),
}

/// Resource limits
pub const MAX_LIMIT: usize = 10000;
pub const MAX_DEPTH: usize = 20;

/// Plan a parsed query into an execution plan.
pub fn plan(query: Query) -> ExecutionPlan {
    match query {
        Query::Select(q) => plan_select(q),
        Query::Show(q) => plan_show(q),
        Query::Find(q) => plan_find(q),
        Query::FindCycles(q) => plan_find_cycles(q),
        Query::Path(q) => plan_path(q),
        Query::Analyze(q) => plan_analyze(q),
        Query::Describe(q) => plan_describe(q),
    }
}

fn plan_select(q: SelectQuery) -> ExecutionPlan {
    let mut sql = String::new();

    // SELECT clause
    sql.push_str("SELECT ");
    // Check for bare SELECT * (not COUNT(*) or other aggregates)
    let is_bare_star = q.fields.is_empty()
        || (q.fields.len() == 1 && q.fields[0].is_star && q.fields[0].aggregate.is_none());
    if is_bare_star {
        sql.push_str("id, type, name, file_path, line_start, line_end, complexity");
    } else {
        let field_strs: Vec<String> = q.fields.iter().map(|f| {
            let expr = if let Some(agg) = &f.aggregate {
                let agg_name = match agg {
                    AggregateFunc::Count => "COUNT",
                    AggregateFunc::Avg => "AVG",
                    AggregateFunc::Max => "MAX",
                    AggregateFunc::Min => "MIN",
                    AggregateFunc::Sum => "SUM",
                };
                if f.is_star {
                    format!("{}(*)", agg_name)
                } else {
                    format!("{}({})", agg_name, f.name)
                }
            } else {
                f.name.clone()
            };
            // Add alias if present
            if let Some(alias) = &f.alias {
                format!("{} AS {}", expr, alias)
            } else {
                expr
            }
        }).collect();
        sql.push_str(&field_strs.join(", "));
    }

    // FROM clause
    sql.push_str(" FROM nodes");

    // WHERE clause
    let mut conditions = Vec::new();

    // Filter by node type
    if q.node_type != NodeTypeFilter::Nodes {
        conditions.push(format!("type = '{}'", q.node_type.to_sql_type()));
    }

    // Add user conditions
    if let Some(where_clause) = &q.where_clause {
        for comp in &where_clause.comparisons {
            let cond = format_comparison(comp);
            conditions.push(cond);
        }
    }

    if !conditions.is_empty() {
        sql.push_str(" WHERE ");
        sql.push_str(&conditions.join(" AND "));
    }

    // GROUP BY clause
    if !q.group_by.is_empty() {
        sql.push_str(" GROUP BY ");
        sql.push_str(&q.group_by.join(", "));
    }

    // HAVING clause
    if let Some(having) = &q.having_clause {
        sql.push_str(" HAVING ");
        let having_conds: Vec<String> = having.comparisons.iter()
            .map(format_comparison)
            .collect();
        sql.push_str(&having_conds.join(" AND "));
    }

    // ORDER BY clause
    if !q.order_by.is_empty() {
        sql.push_str(" ORDER BY ");
        let order_strs: Vec<String> = q.order_by.iter().map(|o| {
            if o.descending {
                format!("{} DESC", o.name)
            } else {
                format!("{} ASC", o.name)
            }
        }).collect();
        sql.push_str(&order_strs.join(", "));
    }

    // LIMIT clause
    let limit = q.limit.unwrap_or(100).min(MAX_LIMIT);
    sql.push_str(&format!(" LIMIT {}", limit));

    ExecutionPlan::Sql(sql)
}

fn format_comparison(comp: &Comparison) -> String {
    let op_str = match comp.op {
        ComparisonOp::Eq => "=",
        ComparisonOp::Ne => "!=",
        ComparisonOp::Gt => ">",
        ComparisonOp::Lt => "<",
        ComparisonOp::Gte => ">=",
        ComparisonOp::Lte => "<=",
        ComparisonOp::Like => "LIKE",
        ComparisonOp::In => "IN",
        ComparisonOp::NotIn => "NOT IN",
    };

    let value_str = format_value(&comp.value);

    if matches!(comp.op, ComparisonOp::In | ComparisonOp::NotIn) {
        format!("{} {} ({})", comp.field, op_str, value_str)
    } else {
        format!("{} {} {}", comp.field, op_str, value_str)
    }
}

fn format_value(value: &Value) -> String {
    match value {
        Value::String(s) => format!("'{}'", s.replace('\'', "''")),
        Value::Number(n) => n.to_string(),
        Value::Bool(b) => b.to_string(),
        Value::Null => "NULL".to_string(),
        Value::List(items) => {
            let formatted: Vec<String> = items.iter().map(format_value).collect();
            formatted.join(", ")
        }
    }
}

fn plan_show(q: ShowQuery) -> ExecutionPlan {
    let depth = q.depth.min(MAX_DEPTH);

    let (op_type, edge_types) = match q.show_type {
        ShowType::Dependencies => (GraphOpType::Dependencies, Some(vec!["imports".to_string()])),
        ShowType::Dependents => (GraphOpType::Dependents, Some(vec!["imports".to_string()])),
        ShowType::Callers => (GraphOpType::Dependents, Some(vec!["calls".to_string()])),
        ShowType::Callees => (GraphOpType::Dependencies, Some(vec!["calls".to_string()])),
        ShowType::Impact => (GraphOpType::Impact, None), // Follow all edges for impact
        ShowType::Ancestors => (GraphOpType::Ancestors, None), // Follow all edges for ancestors
        ShowType::Children => (GraphOpType::Children, Some(vec!["contains".to_string()])),
        ShowType::Parents => (GraphOpType::Dependents, Some(vec!["contains".to_string()])),
        ShowType::Inheritance => (GraphOpType::Dependencies, Some(vec!["inherits".to_string()])),
        ShowType::Implementations => (GraphOpType::Dependents, Some(vec!["inherits".to_string()])),
    };

    ExecutionPlan::Graph(GraphOperation {
        op_type,
        target: q.target,
        depth,
        edge_types,
    })
}

fn plan_find(q: FindQuery) -> ExecutionPlan {
    // Convert find conditions to SQL WHERE clauses
    let mut sql = String::from("SELECT id, type, name, file_path, line_start, line_end, complexity FROM nodes");
    let mut conditions = Vec::new();

    // Filter by node type
    if q.node_type != NodeTypeFilter::Nodes {
        conditions.push(format!("type = '{}'", q.node_type.to_sql_type()));
    }

    // Add condition based on find type
    match &q.condition {
        FindCondition::Matching(pattern) => {
            conditions.push(format!("name LIKE '{}'", pattern.replace('\'', "''")));
        }
        FindCondition::WithDecorator(decorator) => {
            // Would need to check properties JSON
            conditions.push(format!(
                "properties LIKE '%{}%'",
                decorator.replace('\'', "''")
            ));
        }
        _ => {
            // Other conditions require graph traversal
            // For now, just return all nodes of the type
        }
    }

    if !conditions.is_empty() {
        sql.push_str(" WHERE ");
        sql.push_str(&conditions.join(" AND "));
    }

    sql.push_str(" LIMIT 100");

    ExecutionPlan::Sql(sql)
}

fn plan_find_cycles(q: FindCyclesQuery) -> ExecutionPlan {
    ExecutionPlan::Graph(GraphOperation {
        op_type: GraphOpType::Cycles,
        target: String::new(),
        depth: MAX_DEPTH,
        edge_types: q.edge_types,
    })
}

fn plan_path(q: PathQuery) -> ExecutionPlan {
    ExecutionPlan::Graph(GraphOperation {
        op_type: GraphOpType::Path {
            to: q.to_node,
            via: q.via_edge,
        },
        target: q.from_node,
        depth: q.max_depth.min(MAX_DEPTH),
        edge_types: None,
    })
}

fn plan_analyze(q: AnalyzeQuery) -> ExecutionPlan {
    ExecutionPlan::Analysis(AnalysisOperation {
        analysis_type: q.analysis_type,
        target: q.target,
    })
}

fn plan_describe(q: DescribeQuery) -> ExecutionPlan {
    match q.target {
        DescribeTarget::Tables => ExecutionPlan::Schema(SchemaOperation::ListTables),
        DescribeTarget::Columns(nt) => ExecutionPlan::Schema(SchemaOperation::ListColumns(nt)),
        DescribeTarget::NodeType(nt) => ExecutionPlan::Schema(SchemaOperation::DescribeNodeType(nt)),
    }
}
