# LLMCTL MCP Tool Prompt Examples

Each example is a single-line prompt you can paste into a task so tool calls are explicit.

## llmctl_get_model
Explicit:
```text
Call llmctl-mcp tool llmctl_get_model and return the model names as a simple list.
```
Natural:
```text
What models can I query in LLMCTL Studio? List them plainly.
```

## llmctl_get_model_schema
Explicit:
```text
Call llmctl-mcp tool llmctl_get_model_schema with model "Flowchart" and return columns + relationships.
```
Natural:
```text
Show me the LLMCTL Studio schema for Flowchart, including fields and relationships.
```

## llmctl_get_model_rows
Explicit:
```text
Call llmctl-mcp tool llmctl_get_model_rows with {"model":"FlowchartNode","filters":{"flowchart_id":1},"order_by":"id"} and return node IDs + node_type.
```
Natural:
```text
List FlowchartNode rows for flowchart 1 and include each node id and type.
```

## llmctl_get_flowchart
Explicit:
```text
Call llmctl-mcp tool llmctl_get_flowchart with {"limit":50,"order_by":"id"} and return flowchart IDs + names.
```
Natural:
```text
List all flowcharts in LLMCTL Studio with their IDs and names.
```

## llmctl_get_flowchart (by id with graph)
Explicit:
```text
Call llmctl-mcp tool llmctl_get_flowchart with {"flowchart_id":1,"include_graph":true,"include_validation":true} and summarize nodes, edges, and validation errors.
```
Natural:
```text
Show flowchart 1 with its full graph and whether it validates.
```

## llmctl_get_flowchart_graph
Explicit:
```text
Call llmctl-mcp tool llmctl_get_flowchart_graph with {"flowchart_id":1} and return node IDs, edge count, and validation.
```
Natural:
```text
Give me the graph for flowchart 1 and tell me if it is valid.
```

## llmctl_get_flowchart_run
Explicit:
```text
Call llmctl-mcp tool llmctl_get_flowchart_run with {"run_id":1,"include_node_runs":true} and summarize run status and node-run statuses.
```
Natural:
```text
Show flowchart run 1, including all node runs.
```

## llmctl_get_node_run
Explicit:
```text
Call llmctl-mcp tool llmctl_get_node_run with {"flowchart_run_id":1,"order_by":"execution_index"} and return node run id, flowchart_node_id, status.
```
Natural:
```text
List node runs for flowchart run 1 and include node id and status.
```

## llmctl_get_agent_task
Explicit:
```text
Call llmctl-mcp tool llmctl_get_agent_task with {"hours":24,"limit":50,"order_by":"finished_at","descending":true} and return task IDs + statuses.
```
Natural:
```text
What tasks completed in the last 24 hours? List IDs and statuses.
```

## llmctl_get_plan
Explicit:
```text
Call llmctl-mcp tool llmctl_get_plan with {"plan_id":1,"include_stages":true,"include_tasks":true} and summarize stages + tasks.
```
Natural:
```text
Show me plan 1 with all stages and tasks.
```

## llmctl_get_milestone
Explicit:
```text
Call llmctl-mcp tool llmctl_get_milestone with {"limit":50,"order_by":"due_date"} and return milestone IDs, names, status, progress_percent.
```
Natural:
```text
List milestones with status and progress.
```

## llmctl_get_memory
Explicit:
```text
Call llmctl-mcp tool llmctl_get_memory with {"order_by":"updated_at","descending":true,"limit":20}.
```
Natural:
```text
Show the latest memories.
```

## Write/Action Tools Now Available
- `llmctl_create_flowchart`, `llmctl_update_flowchart`, `llmctl_delete_flowchart`
- `llmctl_update_flowchart_graph`
- `start_flowchart`, `cancel_flowchart_run`
- `llmctl_set_flowchart_node_model`
- `llmctl_bind_flowchart_node_mcp`, `llmctl_unbind_flowchart_node_mcp`
- `llmctl_bind_flowchart_node_script`, `llmctl_unbind_flowchart_node_script`, `llmctl_reorder_flowchart_node_scripts`
- `llmctl_create_memory`, `llmctl_update_memory`, `llmctl_delete_memory`
- `llmctl_create_milestone`, `llmctl_update_milestone`, `llmctl_delete_milestone`
- `llmctl_create_plan`, `llmctl_update_plan`, `llmctl_delete_plan`
- `llmctl_create_plan_stage`, `llmctl_update_plan_stage`, `llmctl_delete_plan_stage`
- `llmctl_create_plan_task`, `llmctl_update_plan_task`, `llmctl_delete_plan_task`
