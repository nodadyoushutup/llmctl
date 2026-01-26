# LLMCTL MCP tool prompt examples

Each example is a single-line prompt you can paste into a task. The intent is to make the tool call unambiguous.

This first section only covers read-only tools that fetch data from the LLMCTL Studio DB.

## llmctl_get_model
Explicit: (verified - note, it gets all known flask models and we have a Models we can set up in our DB, how do we want to handle that? maybe we call them something else, maybe we clarify this tool or make a second tool?)
```text
Call llmctl-mcp tool llmctl_get_model and return the model names as a simple list.
```
Natural: (verified, same note as above, also took 2 tries)
```text
What models can I query in LLMCTL Studio? List them plainly.
```

## llmctl_get_model_schema
Explicit: (verified)
```text
Call llmctl-mcp tool llmctl_get_model_schema with model "Pipeline" and return the columns + relationships.
```
Natural: (verified)
```text
Show me the LLMCTL Studio schema for the Pipeline model, including its fields and relationships.
```

## llmctl_get_model_rows
Explicit:
```text
Call llmctl-mcp tool llmctl_get_model_rows with {"model":"PipelineStep","filters":{"pipeline_id":1},"order_by":"step_order"} and return step IDs + task_template_id.
```
Natural:
```text
List PipelineStep rows for pipeline ID 1, ordered by step_order, and include step IDs + task_template_id.
```

## llmctl_get_pipeline
Explicit: (verified)
```text
Call llmctl-mcp tool llmctl_get_pipeline with {"limit":50,"order_by":"id"} and return pipeline IDs + names only.
```
Natural: (verified)
```text
List the LLMCTL Studio pipelines and include each ID and name.
```

## llmctl_get_pipeline (by id)
Explicit: (failed, doesnt look like it used the tool)
```text
Call llmctl-mcp tool llmctl_get_pipeline with {"pipeline_id":1,"include_steps":true} and summarize the pipeline ID 1 name + steps.
```
Natural: (failed)
```text
Show me LLMCTL Studio pipeline ID 1 with its steps.
```

## llmctl_get_agent_task
Explicit: (verified)
```text
Call llmctl-mcp tool llmctl_get_agent_task with {"hours":24,"limit":50,"order_by":"finished_at","descending":true} and return task IDs + statuses.
```
Natural:
```text
What LLMCTL Studio tasks completed in the last 24 hours? List their IDs and statuses.
```

## (Write / action tools)
Write/action tools are intentionally omitted for now to keep the prompt list focused on read-only queries. We can add them back once the read tools are behaving as expected.
