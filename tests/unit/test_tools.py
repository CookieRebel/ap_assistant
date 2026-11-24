from ap_assistant import tools


def test_hanging_po_call_is_attempted_three_times_then_unavailable():
    events = []
    result = tools.call_tool(tools.get_purchase_order, "PO-4004", events.append, timeout=0.2)

    assert result is None
    assert [e["attempt"] for e in events] == [1, 2, 3]
    assert {e["outcome"] for e in events} == {"timeout"}
    assert all(e["duration_ms"] >= 0 for e in events)


def test_successful_call_is_attempted_once():
    events = []
    po = tools.call_tool(tools.get_purchase_order, "PO-4001", events.append)

    assert po.po_number == "PO-4001"
    assert [e["outcome"] for e in events] == ["ok"]


def test_vendor_record_exposes_only_the_last_4_account_digits():
    events = []
    vendor = tools.call_tool(tools.get_vendor_record, "V-100", events.append)

    assert vendor.bank_last4 == "4417"
    dumped = vendor.model_dump_json() + str(events)
    assert "10234417" not in dumped


def test_history_matches_normalised_invoice_number():
    history = tools.check_invoice_history("INV-2002")

    assert [m.history_id for m in history.matches] == ["HIST-0091"]
