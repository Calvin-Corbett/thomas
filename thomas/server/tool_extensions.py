"""Optional domain-module tool registrations for Thomas.

Each entry is tried with graceful fallback — if a module is missing
or broken the server/CLI still starts normally.
"""

import logging

_log = logging.getLogger(__name__)

_OPTIONAL_TOOL_MODULES = [
    ("thomas.tools.engineering", "register_engineering_tools"),
    ("thomas.api_gateway.tools", "register_api_gateway_tools"),
    ("thomas.asset_studio.tools", "register_asset_studio_tools"),
    ("thomas.audio_engine.tools", "register_audio_engine_tools"),
    ("thomas.behavior_tree.tools", "register_behavior_tree_tools"),
    ("thomas.bi_engine.tools", "register_bi_engine_tools"),
    ("thomas.bioinformatics.tools", "register_bioinformatics_tools"),
    ("thomas.blockchain.tools", "register_blockchain_tools"),
    ("thomas.caching.tools", "register_caching_tools"),
    ("thomas.cad.tools", "register_cad_tools"),
    ("thomas.canvas.tools", "register_canvas_tools"),
    ("thomas.cdn.tools", "register_cdn_tools"),
    ("thomas.chain.tools", "register_chain_tools"),
    ("thomas.channels.tools", "register_channels_tools"),
    ("thomas.chatbot.tools", "register_chatbot_tools"),
    ("thomas.climate.tools", "register_climate_tools"),
    ("thomas.codegen.tools", "register_codegen_tools"),
    ("thomas.codex.tools", "register_codex_tools"),
    ("thomas.columnar.tools", "register_columnar_tools"),
    ("thomas.companion.tools", "register_companion_tools"),
    ("thomas.compiler_infra.tools", "register_compiler_infra_tools"),
    ("thomas.config_mgmt.tools", "register_config_mgmt_tools"),
    ("thomas.containers.tools", "register_containers_tools"),
    ("thomas.cqrs.tools", "register_cqrs_tools"),
    ("thomas.crews.tools", "register_crews_tools"),
    ("thomas.crm.tools", "register_crm_tools"),
    # ("thomas.crypto.tools", "register_crypto_tools"),  # stub-only placeholder
    ("thomas.cv.tools", "register_cv_tools"),
    ("thomas.data_catalog.tools", "register_data_catalog_tools"),
    ("thomas.data_pipeline.tools", "register_data_pipeline_tools"),
    ("thomas.data_quality.tools", "register_data_quality_tools"),
    ("thomas.data_warehouse.tools", "register_data_warehouse_tools"),
    ("thomas.dataframe.tools", "register_dataframe_tools"),
    ("thomas.db_internals.tools", "register_db_internals_tools"),
    ("thomas.debug.tools", "register_debug_tools"),
    ("thomas.demo.tools", "register_demo_tools"),
    ("thomas.devops_platform.tools", "register_devops_platform_tools"),
    ("thomas.dns.tools", "register_dns_tools"),
    ("thomas.doc_processing.tools", "register_doc_processing_tools"),
    ("thomas.docdb.tools", "register_docdb_tools"),
    ("thomas.ecs.tools", "register_ecs_tools"),
    ("thomas.eda.tools", "register_eda_tools"),
    ("thomas.email_protocol.tools", "register_email_protocol_tools"),
    ("thomas.energy.tools", "register_energy_tools"),
    ("thomas.erp.tools", "register_erp_tools"),
    ("thomas.etl_monitor.tools", "register_etl_monitor_tools"),
    ("thomas.event_bus.tools", "register_event_bus_tools"),
    ("thomas.event_platform.tools", "register_event_platform_tools"),
    ("thomas.flows.tools", "register_flows_tools"),
    ("thomas.formal_verify.tools", "register_formal_verify_tools"),
    ("thomas.game_ai.tools", "register_game_ai_tools"),
    ("thomas.gaming_platform.tools", "register_gaming_platform_tools"),
    ("thomas.gateway.tools", "register_gateway_tools"),
    # ("thomas.geospatial.tools", "register_geospatial_tools"),  # stub-only placeholder
    # ("thomas.gis.tools", "register_gis_tools"),  # stub-only placeholder
    ("thomas.graph_analytics.tools", "register_graph_analytics_tools"),
    ("thomas.graph_engine.tools", "register_graph_engine_tools"),
    ("thomas.graphdb.tools", "register_graphdb_tools"),
    ("thomas.graphics3d.tools", "register_graphics3d_tools"),
    ("thomas.groupchat.tools", "register_groupchat_tools"),
    ("thomas.http2.tools", "register_http2_tools"),
    ("thomas.human_loop.tools", "register_human_loop_tools"),
    ("thomas.image_proc.tools", "register_image_proc_tools"),
    ("thomas.intake.tools", "register_intake_tools"),
    ("thomas.investigation.tools", "register_investigation_tools"),
    ("thomas.iot_platform.tools", "register_iot_platform_tools"),
    ("thomas.jobs.tools", "register_jobs_tools"),
    ("thomas.knowledge_graph.tools", "register_knowledge_graph_tools"),
    ("thomas.kvstore.tools", "register_kvstore_tools"),
    ("thomas.learning.tools", "register_learning_tools"),
    ("thomas.library.tools", "register_library_tools"),
    ("thomas.load_balancer.tools", "register_load_balancer_tools"),
    ("thomas.loaders.tools", "register_loaders_tools"),
    ("thomas.logging_framework.tools", "register_logging_framework_tools"),
    ("thomas.markdown.tools", "register_markdown_tools"),
    ("thomas.marketplace.tools", "register_marketplace_tools"),
    ("thomas.message_queue.tools", "register_message_queue_tools"),
    ("thomas.messages.tools", "register_messages_tools"),
    ("thomas.model_serving.tools", "register_model_serving_tools"),
    ("thomas.monitoring.tools", "register_monitoring_tools"),
    ("thomas.multi_cloud.tools", "register_multi_cloud_tools"),
    ("thomas.music.tools", "register_music_tools"),
    # ("thomas.networking_deep.tools", "register_networking_deep_tools"),  # stub-only placeholder
    ("thomas.nlg.tools", "register_nlg_tools"),
    ("thomas.nlu.tools", "register_nlu_tools"),
    ("thomas.nodes.tools", "register_nodes_tools"),
    ("thomas.notifications.tools", "register_notifications_tools"),
    ("thomas.notify.tools", "register_notify_tools"),
    ("thomas.olap.tools", "register_olap_tools"),
    ("thomas.openclaw_compat.tools", "register_openclaw_compat_tools"),
    ("thomas.orchestrator.tools", "register_orchestrator_tools"),
    ("thomas.os_kernel.tools", "register_os_kernel_tools"),
    ("thomas.parsers.tools", "register_parsers_tools"),
    ("thomas.pathfinding.tools", "register_pathfinding_tools"),
    ("thomas.patterns.tools", "register_patterns_tools"),
    ("thomas.pentest.tools", "register_pentest_tools"),
    ("thomas.physics.tools", "register_physics_tools"),
    ("thomas.platform_compat.tools", "register_platform_compat_tools"),
    ("thomas.policy.tools", "register_policy_tools"),
    ("thomas.preferences.tools", "register_preferences_tools"),
    ("thomas.procgen.tools", "register_procgen_tools"),
    ("thomas.project_mgmt.tools", "register_project_mgmt_tools"),
    ("thomas.prompts.tools", "register_prompts_tools"),
    ("thomas.quic.tools", "register_quic_tools"),
    ("thomas.realtime.tools", "register_realtime_tools"),
    ("thomas.recommender.tools", "register_recommender_tools"),
    ("thomas.regex_engine.tools", "register_regex_engine_tools"),
    ("thomas.robotics_deep.tools", "register_robotics_deep_tools"),
    ("thomas.rules.tools", "register_rules_tools"),
    ("thomas.scheduler_deep.tools", "register_scheduler_deep_tools"),
    ("thomas.schema.tools", "register_schema_tools"),
    ("thomas.search_engine.tools", "register_search_engine_tools"),
    ("thomas.secrets.tools", "register_secrets_tools"),
    ("thomas.security.tools", "register_security_tools"),
    ("thomas.serialization.tools", "register_serialization_tools"),
    ("thomas.service_mesh.tools", "register_service_mesh_tools"),
    ("thomas.siem.tools", "register_siem_tools"),
    ("thomas.signal_proc.tools", "register_signal_proc_tools"),
    ("thomas.simulation.tools", "register_simulation_tools"),
    ("thomas.smart_home.tools", "register_smart_home_tools"),
    ("thomas.social_platform.tools", "register_social_platform_tools"),
    ("thomas.stats.tools", "register_stats_tools"),
    ("thomas.task_queue.tools", "register_task_queue_tools"),
    ("thomas.telecom.tools", "register_telecom_tools"),
    ("thomas.template_engine.tools", "register_template_engine_tools"),
    ("thomas.tracing.tools", "register_tracing_tools"),
    ("thomas.tray_agent.tools", "register_tray_agent_tools"),
    ("thomas.tsdb.tools", "register_tsdb_tools"),
    ("thomas.units.tools", "register_units_tools"),
    ("thomas.upgrade.tools", "register_upgrade_tools"),
    ("thomas.validation.tools", "register_validation_tools"),
    ("thomas.vision.tools", "register_vision_tools"),
    ("thomas.visualization.tools", "register_visualization_tools"),
    ("thomas.voice.tools", "register_voice_tools"),
    ("thomas.waf.tools", "register_waf_tools"),
    ("thomas.watcher.tools", "register_watcher_tools"),
    ("thomas.webhooks.tools", "register_webhooks_tools"),
    ("thomas.webrtc.tools", "register_webrtc_tools"),
    ("thomas.workflow_v2.tools", "register_workflow_v2_tools"),
]


def _try_import(module_path: str, func_name: str):
    try:
        mod = __import__(module_path, fromlist=[func_name])
        return getattr(mod, func_name)
    except (ImportError, ModuleNotFoundError, AttributeError):
        return None
    except Exception as exc:
        _log.debug("Skipping optional tool module %s.%s: %s", module_path, func_name, exc)
        return None


def register_all_optional_tools(registry) -> int:
    """Register all optional domain tools. Returns count of successfully registered modules."""
    count = 0
    for mod_path, func_name in _OPTIONAL_TOOL_MODULES:
        fn = _try_import(mod_path, func_name)
        if fn is not None:
            try:
                fn(registry)
                count += 1
            except Exception as exc:
                _log.debug("Skipping %s: %s", func_name, exc)
    _log.info("Loaded %d/%d optional tool modules", count, len(_OPTIONAL_TOOL_MODULES))
    return count
