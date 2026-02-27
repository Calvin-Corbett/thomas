"""
Pre-built Workflow Templates

Common workflow templates ready to use:
- Daily standup: Gather updates, summarize, send to Slack
- File processor: Watch folder, process new files
- PR review: Analyze code changes, post comments
- Incident response: Gather logs, analyze, notify
- Data pipeline: Extract, transform, load (ETL)

Templates provide a starting point and can be customized.
"""

from __future__ import annotations

from .models import ErrorAction, StepConfig, StepType, Workflow


def create_daily_standup_workflow() -> Workflow:
    """Create daily standup workflow.

    Gathers updates from team members, summarizes, and sends to Slack.

    Returns:
        Workflow definition
    """
    return Workflow(
        workflow_id="daily_standup",
        name="Daily Standup",
        description="Gather team updates, summarize, and post to Slack",
        steps={
            "gather_updates": StepConfig(
                step_id="gather_updates",
                step_type=StepType.TOOL_CALL,
                config={
                    "tool_name": "slack",
                    "tool_params": {
                        "action": "post_message",
                        "channel": "#standup",
                        "text": "Please provide your standup update",
                    },
                },
                error_action=ErrorAction.SKIP,
                all_next="wait_for_responses",
            ),
            "wait_for_responses": StepConfig(
                step_id="wait_for_responses",
                step_type=StepType.WAIT,
                config={
                    "duration_seconds": 300,  # 5 minutes
                    "until_condition": "all_responses_received",
                },
                all_next="summarize_updates",
            ),
            "summarize_updates": StepConfig(
                step_id="summarize_updates",
                step_type=StepType.LLM_PROMPT,
                config={
                    "prompt": "Summarize these standup updates: ${updates}",
                    "model": "gpt-4",
                    "temperature": 0.7,
                },
                error_action=ErrorAction.ABORT,
                all_next="post_summary",
            ),
            "post_summary": StepConfig(
                step_id="post_summary",
                step_type=StepType.TOOL_CALL,
                config={
                    "tool_name": "slack",
                    "tool_params": {
                        "action": "post_message",
                        "channel": "#standup",
                        "text": "${summary}",
                    },
                },
                error_action=ErrorAction.SKIP,
                all_next=None,
            ),
        },
        entry_step="gather_updates",
    )


def create_file_processor_workflow() -> Workflow:
    """Create file processor workflow.

    Watches a folder for new files and processes them.

    Returns:
        Workflow definition
    """
    return Workflow(
        workflow_id="file_processor",
        name="File Processor",
        description="Watch folder, process new files, store results",
        steps={
            "validate_file": StepConfig(
                step_id="validate_file",
                step_type=StepType.CONDITION,
                config={
                    "condition": "file_extension in ['.csv', '.json', '.txt']",
                },
                next_steps={
                    "success": "process_file",
                    "failure": "skip_file",
                },
            ),
            "process_file": StepConfig(
                step_id="process_file",
                step_type=StepType.TOOL_CALL,
                config={
                    "tool_name": "file_processor",
                    "tool_params": {
                        "file_path": "${file_path}",
                        "action": "parse",
                    },
                },
                error_action=ErrorAction.RETRY,
                max_retries=3,
                all_next="store_results",
            ),
            "store_results": StepConfig(
                step_id="store_results",
                step_type=StepType.TOOL_CALL,
                config={
                    "tool_name": "database",
                    "tool_params": {
                        "action": "insert",
                        "table": "processed_files",
                        "data": "${processed_data}",
                    },
                },
                error_action=ErrorAction.ABORT,
                all_next=None,
            ),
            "skip_file": StepConfig(
                step_id="skip_file",
                step_type=StepType.TOOL_CALL,
                config={
                    "tool_name": "logging",
                    "tool_params": {
                        "level": "info",
                        "message": "Skipped file: ${file_path}",
                    },
                },
                all_next=None,
            ),
        },
        entry_step="validate_file",
    )


def create_pr_review_workflow() -> Workflow:
    """Create PR review workflow.

    Triggered on new PR, analyzes code and posts review.

    Returns:
        Workflow definition
    """
    return Workflow(
        workflow_id="pr_review",
        name="PR Review",
        description="On new PR, analyze code, post review comments",
        steps={
            "fetch_diff": StepConfig(
                step_id="fetch_diff",
                step_type=StepType.TOOL_CALL,
                config={
                    "tool_name": "github",
                    "tool_params": {
                        "action": "get_pr_diff",
                        "pr_number": "${pr_number}",
                    },
                },
                error_action=ErrorAction.ABORT,
                all_next="analyze_code",
            ),
            "analyze_code": StepConfig(
                step_id="analyze_code",
                step_type=StepType.LLM_PROMPT,
                config={
                    "prompt": "Review this code diff and provide detailed feedback:\n${diff}",
                    "model": "gpt-4",
                    "temperature": 0.5,
                },
                error_action=ErrorAction.SKIP,
                all_next="post_review",
            ),
            "post_review": StepConfig(
                step_id="post_review",
                step_type=StepType.TOOL_CALL,
                config={
                    "tool_name": "github",
                    "tool_params": {
                        "action": "post_review_comment",
                        "pr_number": "${pr_number}",
                        "body": "${analysis}",
                    },
                },
                error_action=ErrorAction.SKIP,
                all_next=None,
            ),
        },
        entry_step="fetch_diff",
    )


def create_incident_response_workflow() -> Workflow:
    """Create incident response workflow.

    Triggered on alert, gathers logs, analyzes, and notifies team.

    Returns:
        Workflow definition
    """
    return Workflow(
        workflow_id="incident_response",
        name="Incident Response",
        description="On alert, gather logs, analyze, notify team",
        steps={
            "gather_logs": StepConfig(
                step_id="gather_logs",
                step_type=StepType.TOOL_CALL,
                config={
                    "tool_name": "logging",
                    "tool_params": {
                        "action": "query",
                        "filter": "${alert_filter}",
                        "time_range": "1h",
                    },
                },
                error_action=ErrorAction.ABORT,
                all_next="analyze_logs",
            ),
            "analyze_logs": StepConfig(
                step_id="analyze_logs",
                step_type=StepType.LLM_PROMPT,
                config={
                    "prompt": "Analyze these error logs and identify root cause:\n${logs}",
                    "model": "gpt-4",
                    "temperature": 0.3,
                },
                error_action=ErrorAction.SKIP,
                all_next="notify_team",
            ),
            "notify_team": StepConfig(
                step_id="notify_team",
                step_type=StepType.TOOL_CALL,
                config={
                    "tool_name": "slack",
                    "tool_params": {
                        "action": "post_message",
                        "channel": "#incidents",
                        "text": "INCIDENT: ${analysis}",
                    },
                },
                error_action=ErrorAction.SKIP,
                all_next="request_approval",
            ),
            "request_approval": StepConfig(
                step_id="request_approval",
                step_type=StepType.APPROVAL,
                config={
                    "message": "Approve incident remediation action?",
                    "timeout_seconds": 300,
                },
                next_steps={
                    "approved": "execute_remediation",
                    "rejected": "escalate",
                },
            ),
            "execute_remediation": StepConfig(
                step_id="execute_remediation",
                step_type=StepType.TOOL_CALL,
                config={
                    "tool_name": "incident_response",
                    "tool_params": {
                        "action": "remediate",
                        "incident_id": "${incident_id}",
                    },
                },
                error_action=ErrorAction.ABORT,
                all_next=None,
            ),
            "escalate": StepConfig(
                step_id="escalate",
                step_type=StepType.TOOL_CALL,
                config={
                    "tool_name": "slack",
                    "tool_params": {
                        "action": "post_message",
                        "channel": "#sre-oncall",
                        "text": "ESCALATION: ${analysis}",
                    },
                },
                all_next=None,
            ),
        },
        entry_step="gather_logs",
    )


def create_data_pipeline_workflow() -> Workflow:
    """Create data pipeline (ETL) workflow.

    Extract from source, transform, load to destination.

    Returns:
        Workflow definition
    """
    return Workflow(
        workflow_id="data_pipeline",
        name="Data Pipeline",
        description="Extract from source, transform, load to destination",
        steps={
            "extract": StepConfig(
                step_id="extract",
                step_type=StepType.TOOL_CALL,
                config={
                    "tool_name": "data_extractor",
                    "tool_params": {
                        "source": "${source_type}",
                        "query": "${source_query}",
                    },
                },
                error_action=ErrorAction.ABORT,
                max_retries=2,
                all_next="transform",
            ),
            "transform": StepConfig(
                step_id="transform",
                step_type=StepType.LOOP,
                config={
                    "items": "${extracted_data}",
                    "body_step": "process_item",
                    "item_var": "row",
                },
                all_next="load",
            ),
            "process_item": StepConfig(
                step_id="process_item",
                step_type=StepType.LLM_PROMPT,
                config={
                    "prompt": "Transform this record: ${row}",
                    "model": "gpt-4",
                },
                error_action=ErrorAction.SKIP,
                all_next=None,
            ),
            "load": StepConfig(
                step_id="load",
                step_type=StepType.TOOL_CALL,
                config={
                    "tool_name": "data_loader",
                    "tool_params": {
                        "destination": "${destination_type}",
                        "table": "${destination_table}",
                        "data": "${transformed_data}",
                    },
                },
                error_action=ErrorAction.ABORT,
                all_next="notify_completion",
            ),
            "notify_completion": StepConfig(
                step_id="notify_completion",
                step_type=StepType.TOOL_CALL,
                config={
                    "tool_name": "slack",
                    "tool_params": {
                        "action": "post_message",
                        "channel": "${notification_channel}",
                        "text": "Data pipeline completed. Rows processed: ${row_count}",
                    },
                },
                error_action=ErrorAction.SKIP,
                all_next=None,
            ),
        },
        entry_step="extract",
    )
