select
  t.project,
  count(*) as matching_tool_rows,
  count(distinct c.turn_id) as matching_turns,
  count(distinct c.thread_id) as matching_threads,
  max(c.event_timestamp) as last_event
from thread_memory.tool_calls c
join thread_memory.threads t on t.thread_id = c.thread_id
where coalesce(c.command, '') ilike '%model-fit%'
   or coalesce(c.raw_arguments, '') ilike '%model-fit%'
   or coalesce(c.output_preview, '') ilike '%model-fit%'
group by t.project
order by matching_tool_rows desc;
