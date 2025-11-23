#!/usr/bin/env python3
"""Helper script to run the service validator from the command line."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.services.validation.models import ClientSubmission
from src.services.validation.validator import load_default_validator


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a sample client submission against service metadata.")
    parser.add_argument("service_id", help="Service identifier to validate against")
    parser.add_argument("client_name", help="Client name")
    parser.add_argument("preferred_language", choices=["en", "fr"], help="Preferred communication language")
    parser.add_argument("preferred_channel", help="Desired communication channel (email, tel, etc.)")
    parser.add_argument("--email", dest="email", help="Optional contact email")
    parser.add_argument("--sin", dest="sin", help="Social Insurance Number (if required)")
    parser.add_argument("--cra", dest="cra", help="CRA Business Number (if required)")
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/processed/accessibility_ai.db"),
        help="SQLite database containing service metadata",
    )
    parser.add_argument(
        "--details",
        dest="details",
        help="Extra free-text details for the submission",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    validator = load_default_validator(args.database)
    submission = ClientSubmission(
        service_id=args.service_id,
        preferred_language=args.preferred_language,
        preferred_channel=args.preferred_channel,
        client_name=args.client_name,
        contact_email=args.email,
        sin=args.sin,
        cra_business_number=args.cra,
        additional_details=args.details,
    )
    result = validator.validate(submission)
    print(json.dumps(result.model_dump(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
