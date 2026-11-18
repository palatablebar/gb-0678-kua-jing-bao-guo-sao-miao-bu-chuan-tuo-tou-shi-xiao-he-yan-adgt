import csv,io,json
def build_archive(run):
    stream=io.StringIO(newline="");writer=csv.writer(stream)
    writer.writerow(["run_id","input_sha256","rule_version","kind","source_lines","reason","evidence"])
    meta=run["manifest"]
    for row in run["stages"][-1]["rows"]:
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"accepted",json.dumps(row.get("_sources",[])),row.get("status",""),json.dumps(row,ensure_ascii=False)])
    for row in run["stages"][-1].get("cumulative_quarantine",[]):
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"quarantine",json.dumps(row.get("_sources",[])),row.get("reason",""),json.dumps(row,ensure_ascii=False)])
    # \u505c\u8fd0\u514d\u8d23\u8bc1\u636e\uff1a\u9010\u5305\u7ed3\u8bba\u3001\u4f9d\u636e\u516c\u544a\u3001\u514d\u8d23\u533a\u95f4\u3001\u8d54\u4ed8\u53d8\u5316\uff0c\u968f\u6279\u6b21\u552f\u4e00\u5c01\u5b58
    if len(run["stages"])>=8:
        for row in run["stages"][7]["rows"]:
            evidence={"waiver_decision":row.get("waiver_decision"),"waiver_pieces":row.get("waiver_pieces",[]),
                      "relief_hours":row.get("relief_hours"),"original_expected":row.get("original_expected"),
                      "adjusted_expected":row.get("adjusted_expected"),"comp_change":row.get("comp_change"),
                      "adjusted_sla":row.get("adjusted_sla")}
            writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"waiver",
                             json.dumps(row.get("_sources",[])),row.get("waiver_reason",""),json.dumps(evidence,ensure_ascii=False)])
    return "\ufeff"+stream.getvalue()
