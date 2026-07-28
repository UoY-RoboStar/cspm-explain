import csv

def _remove_assertions(csp:str)->str:
    new_lines = []
    csp_lines = (csp.splitlines())
    for line in csp_lines:
        if not line.startswith("assert"):
            new_lines.append(line)

    return "\n".join(new_lines)

def _append_assertion(csp: str, assertion:str) -> str:
    return csp+"\n"+"assert "+assertion

def _parse_csv_entry(entry)->tuple[str,str,str,str,str]:
    csp = entry[0]
    original_csp = entry[0]
    assertion = entry[1]
    run_assertion = entry[2]
    passed = entry[3]
    counterexample = entry[5]

    csp = _remove_assertions(csp)
    if run_assertion:
        csp = _append_assertion(csp, run_assertion)
    else:
        csp = _append_assertion(csp, assertion)

    return csp,assertion,passed,counterexample,original_csp

def parse_csv(csv_file)->list[list[str]]:
    with open(csv_file, "r", newline='') as f:
        reader = csv.reader(f, delimiter=',', quotechar='"')
        next(reader)
        try:
            lines = []
            for row in reader:
                csp, assertion, passed, counterexample, original_csp = _parse_csv_entry(row)
                lines.append([csp, assertion, passed, counterexample, original_csp])
        except csv.Error as e:
            print(f'file {csv_file}, line {reader.line_num}: {e}')

    return lines
