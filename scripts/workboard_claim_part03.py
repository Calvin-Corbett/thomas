    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON for suggestion output.")
    args = parser.parse_args(argv)

    workboard_path = Path(args.workboard).expanduser()
    if not workboard_path.is_absolute():
        workboard_path = (ROOT / workboard_path).resolve()

    if not workboard_path.exists():
        print(f"Workboard claim tool: FAIL\n- missing workboard file: {workboard_path}")
        return 1

    try:
        if args.list:
            ok, result = list_claims(workboard_path)
            if not ok:
                print(f"Workboard claim tool: FAIL\n- {result}")
                return 1
            claims = result if isinstance(result, list) else []
            if args.json:
                violations, rows, _tasks, _grab, _issues = claims_gate.evaluate_board(workboard_path)
                if violations:
                    out = {
                        "ok": False,
                        "action": "list",
                        "error": "workboard invalid",
                        "violations": list(violations),
                    }
                else:
                    out = {
                        "ok": True,
                        "action": "list",
                        "active_claim_count": len(rows),
                        "active_claims": [
                            {
                                "agent": claim.agent,
                                "name": claim.name or claim.agent,
                                "role": claim.role or ("worker" if claim.parent else "solo"),
                                "parent": claim.parent or "none",
                                "scope": list(claim.scopes),
                                "task": claim.task,
                                "line_no": int(claim.line_no),
                            }
                            for claim in rows
                        ],
                    }
                print(json.dumps(out, sort_keys=True))
                return 0 if out.get("ok") else 1
            print("Workboard claim tool: PASS")
            if claims:
                for line in claims:
                    print(line)
            else:
                print("- no active claims")
            return 0

        if args.suggest_delegation:
            agent = _resolve_agent(args.agent)
            ok, result = suggest_delegation(
                workboard_path,
                parent_agent=agent,
                max_suggestions=int(args.max_suggestions),
            )
            if not ok:
                if args.json:
                    print('{"ok": false, "action": "suggest_delegation", "error": ' + json.dumps(str(result)) + "}")
                else:
                    print(f"Workboard claim tool: FAIL\n- {result}")
                return 1
            payload = result if isinstance(result, dict) else {}
            if args.json:
                out = {"ok": True, "action": "suggest_delegation", **payload}
                print(json.dumps(out, sort_keys=True))
            else:
                print("Workboard claim tool: PASS")
                print(
                    f"- parent={payload.get('parent_agent')}; name={payload.get('parent_name')}; "
                    f"active_workers={payload.get('active_worker_count')}"
                )
                ready = list(payload.get("ready_suggestions") or [])
                blocked = list(payload.get("blocked_candidates") or [])
                if ready:
                    print("- ready delegation suggestions:")
                    for item in ready:
                        print(f"  - {item.get('task_id')}: {item.get('summary')} " f"(scope={item.get('scope')})")
                        print(f"    {item.get('claim_command')}")
                else:
                    print("- no non-overlapping delegation suggestions available")
                if blocked:
                    print("- blocked candidates:")
                    for item in blocked[:5]:
                        overlaps = ", ".join([str(v) for v in (item.get("overlaps") or [])])
                        print(f"  - {item.get('task_id')} overlaps with: {overlaps}")
                guidance = str(payload.get("guidance") or "").strip()
                if guidance:
                    print(f"- guidance: {guidance}")
            return 0

        if args.dispatch_workers:
            agent = _resolve_agent(args.agent)
            ok, result = dispatch_workers(
                workboard_path,
                parent_agent=agent,
                target_workers=int(args.dispatch_target_workers),
                max_suggestions=int(args.dispatch_max_suggestions),
                release_ready=bool(args.dispatch_release_ready),
                enable_temp_creator=not bool(args.dispatch_no_temp_creator),
                task_manager_agent=str(args.task_manager_agent or DEFAULT_TASK_MANAGER_AGENT),
                notify_task_manager=not bool(args.dispatch_no_temp_creator_notice),
            )
            if not ok:
                if args.json:
                    print('{"ok": false, "action": "dispatch_workers", "error": ' + json.dumps(str(result)) + "}")
                else:
                    print(f"Workboard claim tool: FAIL\n- {result}")
                return 1
            payload = result if isinstance(result, dict) else {}
            if args.json:
                out = {"ok": True, "action": "dispatch_workers", **payload}
                print(json.dumps(out, sort_keys=True))
            else:
                print("Workboard claim tool: PASS")
                print(
                    f"- parent={payload.get('parent_agent')}; name={payload.get('parent_name')}; "
                    f"active_workers={payload.get('active_worker_count')}/{payload.get('target_workers')}"
                )
                released = list(payload.get("released_workers") or [])
                if released:
                    print("- released READY workers:")
                    for worker in released:
                        print(f"  - {worker}")
                claimed = list(payload.get("claimed_workers") or [])
                if claimed:
                    print("- claimed worker lanes:")
                    for item in claimed:
                        print(f"  - {item.get('agent')} => {item.get('task_id')} " f"(scope={item.get('scope')})")
                else:
                    print("- no worker claims created in this dispatch pass")
                temp_payload = payload.get("temp_task_creator")
                if isinstance(temp_payload, dict):
                    temp_status = str(temp_payload.get("status") or "").strip()
                    holder = str(temp_payload.get("holder_agent") or "").strip()
                    manager = str(temp_payload.get("manager_agent") or "").strip()
                    if temp_status and temp_status != "disabled":
                        print(
                            f"- temp-task-creator={temp_status}; holder={holder or 'none'}; "
                            f"manager={manager or 'none'}"
                        )
                guidance = str(payload.get("guidance") or "").strip()
                if guidance:
                    print(f"- guidance: {guidance}")
            return 0

        if args.release_temp_task_creator:
            agent = _resolve_agent(args.agent)
            ok, result = release_temp_task_creator(
                workboard_path,
                actor_agent=agent,
                task_manager_agent=str(args.task_manager_agent or DEFAULT_TASK_MANAGER_AGENT),
            )
            if args.json:
                if ok:
                    out = {"ok": True, "action": "release_temp_task_creator", **(result or {})}
                else:
                    if isinstance(result, dict):
                        out = {"ok": False, "action": "release_temp_task_creator", **result}
                    else:
                        out = {
                            "ok": False,
                            "action": "release_temp_task_creator",
                            "error": str(result),
                        }
                print(json.dumps(out, sort_keys=True))
                return 0 if ok else 1

            if not ok:
                if isinstance(result, dict):
                    err = str(result.get("error") or json.dumps(result, sort_keys=True))
                else:
                    err = str(result)
                print(f"Workboard claim tool: FAIL\n- {err}")
                return 1

            payload = result if isinstance(result, dict) else {}
            print("Workboard claim tool: PASS")
            print(
                f"- task-manager={payload.get('task_manager_agent')}; " f"released={payload.get('released_count', 0)}"
            )
            released_rows = list(payload.get("released") or [])
            if released_rows:
                for row in released_rows:
                    print(f"  - {row.get('holder_agent')} " f"(lease={row.get('lease_agent')})")
            return 0

        if args.claim:
            if not args.scope:
                print("Workboard claim tool: FAIL\n- --scope is required for --claim")
                return 1
            agent = _resolve_agent(args.agent)
            task = _resolve_task(args.task)
            ok, msg = claim(
                workboard_path,
                agent=agent,
                scope=args.scope,
                task=task,
                name=args.name,
                role=args.role,
                parent=args.parent,
                allow_dirty=bool(args.allow_dirty_claim),
                dirty_reason=str(args.dirty_claim_reason or ""),
                allow_presence_override=bool(args.allow_presence_override),
                presence_override_reason=str(args.presence_override_reason or ""),
            )
            if not ok:
                print(f"Workboard claim tool: FAIL\n- {msg}")
                return 1
            print("Workboard claim tool: PASS")
            print(f"- {msg}")
            return 0

        agent = _resolve_agent(args.agent)
        ok, msg = release(
            workboard_path,
            agent=agent,
            allow_dirty=bool(args.allow_dirty_release),
            dirty_reason=str(args.dirty_release_reason or ""),
            allow_presence_override=bool(args.allow_presence_override),
            presence_override_reason=str(args.presence_override_reason or ""),
        )
        if not ok:
            print(f"Workboard claim tool: FAIL\n- {msg}")
            return 1
        print("Workboard claim tool: PASS")
        print(f"- {msg}")
        return 0
    except ValueError as exc:
        print(f"Workboard claim tool: FAIL\n- {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
