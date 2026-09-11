# OracleBridge smoke test — mode: proxy
Generated: 2026-09-12T01:14:22
Database: 

## Summary: FAIL=13, PASS=62
- **PASS**: 62
- **FAIL**: 13 -> fun.012, typ.002, seq.001, ora.005, dml.006, dml.007, pls.010, pls.011, pls.012, pls.013, pls.003, pls.006, pls.008

| Test | Stato | Dettaglio |
|------|-------|-----------|
| san.001 | PASS |  vs oracle: MATCH |
| san.002 | PASS |  vs oracle: MATCH |
| san.003 | PASS |  vs oracle: MATCH |
| san.004 | PASS |  vs oracle: MATCH |
| san.005 | PASS |  vs oracle: MATCH |
| san.006 | PASS |  vs oracle: MATCH |
| san.007 | PASS |  vs oracle: MATCH |
| san.008 | PASS |  vs oracle: MATCH |
| san.009 | PASS |  vs oracle: MATCH |
| san.010 | PASS |  vs oracle: MATCH |
| fun.001 | PASS |  vs oracle: MATCH |
| fun.002 | PASS |  vs oracle: MATCH |
| fun.003 | PASS |  vs oracle: MATCH |
| fun.004 | PASS |  vs oracle: MATCH |
| fun.005 | PASS |  vs oracle: MATCH |
| fun.006 | PASS |  vs oracle: MATCH |
| fun.007 | PASS |  vs oracle: MATCH |
| fun.008 | PASS |  vs oracle: MATCH |
| fun.009 | PASS |  vs oracle: MATCH |
| fun.010 | PASS |  vs oracle: MATCH |
| fun.011 | PASS |  vs oracle: MATCH |
| fun.012 | FAIL | expected rows [[1]], got [['1 00:00:00.000']] vs oracle: N/A |
| fun.013 | PASS |  vs oracle: MATCH |
| fun.014 | PASS |  vs oracle: MATCH |
| fun.015 | PASS |  vs oracle: MATCH |
| fun.016 | PASS |  vs oracle: MATCH |
| fun.017 | PASS |  vs oracle: MATCH |
| fun.018 | PASS |  vs oracle: MATCH |
| typ.001 | PASS |  vs oracle: MATCH |
| typ.002 | FAIL | expected rows [['ciao', 5, 'AB']], got [['ciao', 2, 'AB']] vs oracle: N/A |
| typ.003 | PASS |  vs oracle: MATCH |
| typ.004 | PASS |  vs oracle: MATCH |
| typ.005 | PASS |  vs oracle: MATCH |
| typ.006 | PASS |  vs oracle: MATCH |
| typ.007 | PASS |  vs oracle: MATCH |
| typ.008 | PASS |  vs oracle: MATCH |
| typ.009 | PASS |  vs oracle: MATCH |
| seq.001 | FAIL | expected rows [[0]], got [[-10]] vs oracle: N/A |
| seq.002 | PASS |  vs oracle: MATCH |
| ora.001 | PASS |  vs oracle: MATCH |
| ora.002 | PASS |  vs oracle: MATCH |
| ora.003 | PASS |  vs oracle: MATCH |
| ora.004 | PASS |  vs oracle: MATCH |
| ora.005 | FAIL | unexpected error ORA-00900: ORA-00900: invalid SQL statement vs oracle: N/A |
| ora.006 | PASS |  vs oracle: MATCH |
| ora.007 | PASS |  vs oracle: MATCH |
| ora.008 | PASS |  vs oracle: MATCH |
| ora.009 | PASS |  vs oracle: MATCH |
| ora.010 | PASS |  vs oracle: MATCH |
| dml.001 | PASS |  vs oracle: MATCH |
| dml.002 | PASS |  vs oracle: MATCH |
| dml.003 | PASS |  vs oracle: MATCH |
| dml.004 | PASS |  vs oracle: MATCH |
| dml.005 | PASS |  vs oracle: DIVERGENT |
| dml.006 | FAIL | unexpected error UNKNOWN:InternalError: DPY-5000: internal error: unknown protocol message type 1 at position 10 vs oracle: N/A |
| dml.007 | FAIL | unexpected error UNKNOWN:InternalError: DPY-5000: internal error: unknown protocol message type 2 at position 10 vs oracle: N/A |
| pls.010 | FAIL | unexpected error ORA-06550: ORA-06550: line 1, column 1: vs oracle: N/A |
| pls.011 | FAIL | unexpected error ORA-00900: ORA-00900: TTC function 3 not supported by the proxy vs oracle: N/A |
| pls.012 | FAIL | unexpected error ORA-06550: ORA-06550: line 1, column 1: vs oracle: N/A |
| pls.013 | FAIL | unexpected error ORA-06550: ORA-06550: line 1, column 1: vs oracle: N/A |
| pls.002 | PASS |  vs oracle: MATCH |
| pls.003 | FAIL | expected rows [['KING']], got None vs oracle: N/A |
| pls.004 | PASS |  vs oracle: MATCH |
| pls.005 | PASS |  vs oracle: MATCH |
| pls.006 | FAIL | OUT bind out: expected -20001, got None vs oracle: N/A |
| pls.007 | PASS |  vs oracle: MATCH |
| pls.008 | FAIL | unexpected error ORA-06550: ORA-06550: line 1, column 1: vs oracle: N/A |
| pls.009 | PASS |  vs oracle: MATCH |
| err.001 | PASS |  vs oracle: MATCH |
| err.002 | PASS |  vs oracle: MATCH |
| err.003 | PASS |  vs oracle: MATCH |
| err.004 | PASS |  vs oracle: MATCH |
| err.005 | PASS |  vs oracle: MATCH |
| err.006 | PASS |  vs oracle: MATCH |
| err.007 | PASS |  vs oracle: MATCH |