"""Bounded diagnostics: never serialize exception locals or arbitrary error text."""
from datetime import datetime, timezone
from pathlib import Path
import re

# Only exact, application-owned messages are safe for journals and status output.
# Unknown/provider exceptions still expose their type and code locations, not payloads.
SAFE_MESSAGES = frozenset({
    "Gmail OAuth expired or revoked; reauthorization required",
    "Source text and readable images do not support a useful summary",
    'Invalid synchronous correction',
    'Senior image decision did not cover all locations',
    'Image provider relationship needs independently vetted rules',
    'Image provider relationship lacks first-party public evidence',
    'Image provider relationship not confirmed by public evidence',
    'Image provider evidence page unavailable',
    'Image provider evidence page too large',
    'Invalid image provider evidence',
    'Image location is not a query-free static asset',
    'Image source held: independent provider evidence missing',
    'Synchronous image review unavailable; source held',
    'Senior image resolution incomplete; source held',
    'Final reviewer did not confirm promotional content',
    'Senior handoff acknowledgement missing',
    'Reviewer adapter failed',
    'Image location needs senior investigation; source held',
    'No approved artwork available for visual extraction',
    'Digest summarization failed; nothing sent or marked',
    'Policy changed during workflow; explicit restart required',
    'Prior delivery requires reconciliation',
    'Final content review incomplete',
    'Final review requires preview',
    'Final review missing or stale; sending blocked',
    'Final review changed title coverage',
    'Final review omitted source title',
    'Final description not source quoted',
    'Final description borrowed another image',
    'Title-list profile has no extracted source titles',
    'Review must provide complete title-list evidence',
    'Image evidence unreadable; summary incomplete',
    'Invalid visual evidence',
    'Invalid senior visual-evidence review',
    'Image evidence awaiting senior resolution',
    'Combined source exceeds visual extraction budget',
})


def failure_details(exc, stage):
    chain=[];seen=set();source_id=None
    while exc is not None and id(exc) not in seen and len(chain)<8:
        seen.add(id(exc))
        candidate=getattr(exc,'source_id',None)
        if isinstance(candidate,str) and re.fullmatch(r'[a-fA-F0-9]{1,64}',candidate):
            source_id=candidate
        message=str(exc)
        frames=[];tb=exc.__traceback__
        while tb is not None:
            code=tb.tb_frame.f_code
            frames.append({'file':Path(code.co_filename).name,'function':code.co_name,'line':tb.tb_lineno})
            tb=tb.tb_next
        chain.append({'type':type(exc).__name__,
                      'message':message if message in SAFE_MESSAGES else 'Error text withheld to protect mail and credentials; inspect code locations',
                      'frames':frames[-12:]})
        code=getattr(exc,'returncode',None)
        if isinstance(code,int):chain[-1]['exit_code']=code
        exc=exc.__cause__ if exc.__cause__ is not None else (None if exc.__suppress_context__ else exc.__context__)
    result={'at':datetime.now(timezone.utc).isoformat(),'stage':stage,'chain':chain}
    if source_id:result['source_id']=source_id
    return result
