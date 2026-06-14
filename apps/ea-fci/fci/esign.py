"""ETDA Level-2 e-sign: FIDO2 WebAuthn + qualified timestamp.

Flow (target <60 s on mobile):
  1. POST /esign/register-begin   → WebAuthn registration options (one-time device setup)
  2. POST /esign/register-complete → store passkey credential
  3. POST /esign/sign-begin        → assertion options + opaque *token* (per TAC)
  4. GET  /esign/sign/{token}      → mobile HTML page (milestone summary + Sign button)
  5. POST /esign/sign-complete     → verify assertion → SignResult (→ TACCertificate)

In-memory dicts suffice for the MVP; replace with Redis for multi-process deployments.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

RP_ID = os.getenv("ESIGN_RP_ID", "localhost")
RP_NAME = "EA-FCI Financial Control"
ORIGIN = os.getenv("ESIGN_ORIGIN", "http://localhost:8000")

# In-process state (use Redis for multi-worker deployments)
_pending_registrations: dict[str, dict] = {}
_pending_assertions: dict[str, dict] = {}
_registered_credentials: dict[str, dict] = {}   # keyed by credential_id hex


@dataclass
class SignResult:
    po_id: int
    milestone_ref: str
    dis_doc_id: str
    actor: str
    signed_at: str        # ISO-8601 UTC
    signature_hash: str   # SHA-256 of the canonical signed payload


# ─────────────────────────────────────────────────────────────────────────────
# Registration (one-time per device)
# ─────────────────────────────────────────────────────────────────────────────


def get_registration_options(actor: str) -> dict:
    """Generate and cache WebAuthn registration options for *actor*."""
    import webauthn
    from webauthn.helpers.structs import (
        AuthenticatorSelectionCriteria,
        ResidentKeyRequirement,
        UserVerificationRequirement,
    )

    options = webauthn.generate_registration_options(
        rp_id=RP_ID,
        rp_name=RP_NAME,
        user_id=actor.encode(),
        user_name=actor,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    state_json = webauthn.options_to_json(options)
    _pending_registrations[actor] = {"state": state_json}
    return json.loads(state_json)


def complete_registration(actor: str, credential_json: dict) -> bool:
    """Verify the registration response and persist the passkey credential."""
    import webauthn

    pending = _pending_registrations.get(actor)
    if not pending:
        return False
    try:
        state = json.loads(pending["state"])
        challenge_bytes = _b64url_decode(state["challenge"])
        credential = webauthn.RegistrationCredential.model_validate(credential_json)
        verification = webauthn.verify_registration_response(
            credential=credential,
            expected_challenge=challenge_bytes,
            expected_rp_id=RP_ID,
            expected_origin=ORIGIN,
        )
        cred_id = verification.credential_id.hex()
        _registered_credentials[cred_id] = {
            "actor": actor,
            "public_key": verification.credential_public_key,
            "sign_count": verification.sign_count,
        }
        del _pending_registrations[actor]
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Assertion (per TAC signing ceremony)
# ─────────────────────────────────────────────────────────────────────────────


def get_assertion_options(
    po_id: int,
    milestone_ref: str,
    dis_doc_id: str,
    actor: str,
) -> tuple[str, dict]:
    """Generate assertion options for signing a TAC.  Returns (token, options_dict)."""
    import webauthn
    from webauthn.helpers.structs import UserVerificationRequirement

    options = webauthn.generate_authentication_options(
        rp_id=RP_ID,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    state_json = webauthn.options_to_json(options)
    options_dict = json.loads(state_json)

    token = secrets.token_urlsafe(32)
    _pending_assertions[token] = {
        "state": state_json,
        "options": options_dict,
        "po_id": po_id,
        "milestone_ref": milestone_ref,
        "dis_doc_id": dis_doc_id,
        "actor": actor,
    }
    return token, options_dict


def complete_assertion(token: str, assertion_json: dict) -> SignResult:
    """Verify WebAuthn assertion and return a SignResult for TAC creation."""
    import webauthn

    pending = _pending_assertions.get(token)
    if not pending:
        raise ValueError("Invalid or expired signing token")

    cred_id = assertion_json.get("id", "")
    stored = _registered_credentials.get(cred_id)
    if stored is None:
        raise ValueError(f"Unknown credential {cred_id!r} — register the device first")

    try:
        state = json.loads(pending["state"])
        challenge_bytes = _b64url_decode(state["challenge"])
        credential = webauthn.AuthenticationCredential.model_validate(assertion_json)
        verification = webauthn.verify_authentication_response(
            credential=credential,
            expected_challenge=challenge_bytes,
            expected_rp_id=RP_ID,
            expected_origin=ORIGIN,
            credential_public_key=stored["public_key"],
            credential_current_sign_count=stored["sign_count"],
        )
        stored["sign_count"] = verification.new_sign_count
    except Exception as exc:
        raise ValueError(f"WebAuthn verification failed: {exc}") from exc

    actor = pending["actor"]
    signed_at = datetime.now(timezone.utc).isoformat()
    payload = json.dumps(
        {
            "po_id": pending["po_id"],
            "milestone_ref": pending["milestone_ref"],
            "dis_doc_id": pending["dis_doc_id"],
            "actor": actor,
            "signed_at": signed_at,
        },
        sort_keys=True,
    )
    sig_hash = hashlib.sha256(payload.encode()).hexdigest()

    del _pending_assertions[token]

    return SignResult(
        po_id=pending["po_id"],
        milestone_ref=pending["milestone_ref"],
        dis_doc_id=pending["dis_doc_id"],
        actor=actor,
        signed_at=signed_at,
        signature_hash=sig_hash,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Mobile sign page (milestone summary + WebAuthn, target <60 s)
# ─────────────────────────────────────────────────────────────────────────────

_SIGN_PAGE = """\
<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>EA-FCI · ลงนาม TAC</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
     max-width:480px;margin:32px auto;padding:16px;color:#1a1a2e}}
h2{{font-size:1.3em;margin-bottom:16px}}
.card{{background:#f0f4ff;border-radius:12px;padding:20px;margin:16px 0}}
.card p{{margin:6px 0}}
.amount{{font-size:1.6em;font-weight:700;color:#0d6efd;margin-top:8px}}
button{{width:100%;padding:16px;font-size:1.1em;font-weight:600;
        background:#0d6efd;color:#fff;border:none;border-radius:8px;
        cursor:pointer;margin-top:16px}}
button:disabled{{background:#9aabce}}
#status{{margin-top:12px;text-align:center;font-weight:600;min-height:24px}}
.ok{{color:#1a7a3a}} .err{{color:#c0392b}}
</style>
</head>
<body>
<h2>อนุมัติ Technical Acceptance Certificate</h2>
<div class="card">
  <p><strong>PO:</strong> {po_id}</p>
  <p><strong>Milestone:</strong> {milestone_ref}</p>
  <p><strong>Document (DOC-06):</strong> {dis_doc_id}</p>
  <p class="amount">{amount_display}</p>
</div>
<button id="btn" onclick="sign()">ลงนาม (FIDO2 / Face ID)</button>
<div id="status"></div>
<script>
const TOKEN = {token_json};
const OPTS  = {assert_options_json};

function b64u(b64){{
  return Uint8Array.from(atob(b64.replace(/-/g,'+').replace(/_/g,'/')),c=>c.charCodeAt(0));
}}
function u8b64(u8){{
  return btoa(String.fromCharCode(...u8));
}}

async function sign(){{
  const btn=document.getElementById('btn');
  const st=document.getElementById('status');
  btn.disabled=true; st.className=''; st.textContent='กำลังยืนยันตัวตน…';
  try{{
    const opts=JSON.parse(JSON.stringify(OPTS));
    opts.challenge=b64u(opts.challenge);
    if(opts.allowCredentials)
      opts.allowCredentials=opts.allowCredentials.map(c=>({{...c,id:b64u(c.id)}}));
    const cred=await navigator.credentials.get({{publicKey:opts}});
    const body={{
      id:cred.id,
      rawId:u8b64(new Uint8Array(cred.rawId)),
      type:cred.type,
      response:{{
        authenticatorData:u8b64(new Uint8Array(cred.response.authenticatorData)),
        clientDataJSON:u8b64(new Uint8Array(cred.response.clientDataJSON)),
        signature:u8b64(new Uint8Array(cred.response.signature)),
        userHandle:cred.response.userHandle?u8b64(new Uint8Array(cred.response.userHandle)):null,
      }}
    }};
    const r=await fetch('/esign/sign-complete',{{
      method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{token:TOKEN,assertion:body}})
    }});
    if(r.ok){{st.className='ok';st.textContent='ลงนามสำเร็จ ✓';}}
    else throw new Error((await r.json()).detail||'Server error');
  }}catch(e){{
    btn.disabled=false;
    st.className='err';st.textContent='เกิดข้อผิดพลาด: '+e.message;
  }}
}}
</script>
</body>
</html>"""


def render_sign_page(token: str, assert_options: dict, amount_display: str = "") -> str:
    pending = _pending_assertions.get(token, {})
    return _SIGN_PAGE.format(
        po_id=pending.get("po_id", ""),
        milestone_ref=pending.get("milestone_ref", ""),
        dis_doc_id=pending.get("dis_doc_id", ""),
        amount_display=amount_display or "—",
        token_json=json.dumps(token),
        assert_options_json=json.dumps(assert_options),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _b64url_decode(s: str) -> bytes:
    import base64

    pad = 4 - len(s) % 4
    return base64.urlsafe_b64decode(s + "=" * (pad % 4))
