"""Deterministic offline UBL 2.1 & EN 16931 / Peppol BIS 3.0 validator."""

from __future__ import annotations

import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from lxml import etree

from canarybench.core.schemas import round_half_up

NS_INV = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
NS_CN = "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"
NS_CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
NS_CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"

_MONEY_2DP_RE = re.compile(r"^-?\d+\.\d{2}$")
_PRICE_RE = re.compile(r"^\d+\.\d{2,4}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_VAT_PREFIX_RE = re.compile(r"^([A-Z]{2}|EL)[A-Z0-9-]{2,18}$")
_ISO2_RE = re.compile(r"^[A-Z]{2}$")

_INVOICE_ORDER: dict[str, int] = {
    "CustomizationID": 1,
    "ProfileID": 2,
    "ID": 3,
    "IssueDate": 4,
    "DueDate": 5,
    "InvoiceTypeCode": 6,
    "Note": 7,
    "DocumentCurrencyCode": 8,
    "TaxCurrencyCode": 9,
    "AccountingCost": 10,
    "OrderReference": 11,
    "BillingReference": 12,
    "AdditionalDocumentReference": 13,
    "AccountingSupplierParty": 14,
    "AccountingCustomerParty": 15,
    "Delivery": 16,
    "PaymentMeans": 17,
    "AllowanceCharge": 18,
    "TaxTotal": 19,
    "LegalMonetaryTotal": 20,
    "InvoiceLine": 21,
}

_CREDIT_NOTE_ORDER: dict[str, int] = {
    "CustomizationID": 1,
    "ProfileID": 2,
    "ID": 3,
    "IssueDate": 4,
    "CreditNoteTypeCode": 5,
    "Note": 6,
    "DocumentCurrencyCode": 7,
    "TaxCurrencyCode": 8,
    "AccountingCost": 9,
    "OrderReference": 10,
    "BillingReference": 11,
    "AdditionalDocumentReference": 12,
    "AccountingSupplierParty": 13,
    "AccountingCustomerParty": 14,
    "Delivery": 15,
    "PaymentMeans": 16,
    "AllowanceCharge": 17,
    "TaxTotal": 18,
    "LegalMonetaryTotal": 19,
    "CreditNoteLine": 20,
}


def _local(tag: object) -> str:
    if not isinstance(tag, str):
        return ""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _parse_dec(text: str | None) -> Decimal | None:
    if text is None:
        return None
    try:
        d = Decimal(text.strip())
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def _text(el: etree._Element | None, xpath: str, ns: dict[str, str]) -> str | None:
    if el is None:
        return None
    found = el.find(xpath, namespaces=ns)
    if found is None or found.text is None:
        return None
    return found.text.strip()


def validate_en16931(xml_content: str | bytes) -> list[str]:
    """Validate UBL 2.1 XML against structural order and EN 16931 / Peppol BIS 3.0 BR rules.

    Returns an empty list when valid, or a deterministic list of rule violation messages.
    """
    errors: list[str] = []
    raw_str = xml_content.decode("utf-8") if isinstance(xml_content, bytes) else xml_content
    if "<!DOCTYPE" in raw_str.upper() or "<!ENTITY" in raw_str.upper():
        return ["SEC-XML-01: DOCTYPE and ENTITY declarations are forbidden"]

    parser = etree.XMLParser(resolve_entities=False, no_network=True, dtd_validation=False)
    try:
        root = etree.fromstring(raw_str.encode("utf-8"), parser=parser)
    except etree.XMLSyntaxError as exc:
        return [f"XML-SYNTAX: {exc}"]

    root_tag = root.tag
    if root_tag == f"{{{NS_INV}}}Invoice":
        doc_kind = "Invoice"
        order_map = _INVOICE_ORDER
        line_name = "InvoiceLine"
        qty_name = "InvoicedQuantity"
        type_code_name = "InvoiceTypeCode"
        expected_type_code = "380"
    elif root_tag == f"{{{NS_CN}}}CreditNote":
        doc_kind = "CreditNote"
        order_map = _CREDIT_NOTE_ORDER
        line_name = "CreditNoteLine"
        qty_name = "CreditedQuantity"
        type_code_name = "CreditNoteTypeCode"
        expected_type_code = "381"
    else:
        return [f"UBL-ROOT-01: Invalid root element {root_tag!r}"]

    ns = {"cac": NS_CAC, "cbc": NS_CBC}

    # 1. XSD child element order & namespace check
    last_rank = 0
    for child in root:
        if not isinstance(child.tag, str):
            continue
        name = _local(child.tag)
        if name not in order_map:
            errors.append(f"UBL-XSD-01: Unexpected child element <{name}> in {doc_kind}")
            continue
        rank = order_map[name]
        if rank < last_rank:
            errors.append(f"UBL-XSD-02: Element <{name}> out of UBL 2.1 schema order")
        last_rank = rank

    # Forbidden elements under Peppol BIS 3.0
    if root.find("cac:TaxExchangeRate", namespaces=ns) is not None:
        errors.append("UBL-CR-490: cac:TaxExchangeRate is forbidden in EN 16931 / Peppol")

    # 2. Header identifiers & BR-01..BR-09
    custom_id = _text(root, "cbc:CustomizationID", ns)
    if custom_id != "urn:cen.eu:en16931:2017":
        errors.append(f"BR-01: CustomizationID must be urn:cen.eu:en16931:2017, got {custom_id!r}")

    doc_id = _text(root, "cbc:ID", ns)
    if not doc_id:
        errors.append("BR-02: Document ID (BT-1) must not be empty")

    issue_date = _text(root, "cbc:IssueDate", ns)
    if not issue_date or not _DATE_RE.match(issue_date):
        errors.append(f"BR-03: IssueDate (BT-2) must be YYYY-MM-DD, got {issue_date!r}")

    type_code = _text(root, f"cbc:{type_code_name}", ns)
    if type_code != expected_type_code:
        errors.append(f"BR-04: {type_code_name} must be {expected_type_code}, got {type_code!r}")

    doc_ccy = _text(root, "cbc:DocumentCurrencyCode", ns)
    if not doc_ccy or len(doc_ccy) != 3 or not doc_ccy.isalpha():
        errors.append(f"BR-05: DocumentCurrencyCode (BT-5) invalid: {doc_ccy!r}")
        doc_ccy = "EUR"

    tax_ccy = _text(root, "cbc:TaxCurrencyCode", ns)
    if tax_ccy is not None and tax_ccy == doc_ccy:
        errors.append("PEPPOL-EN16931-R005: TaxCurrencyCode (BT-6) must differ from BT-5")

    if doc_kind == "CreditNote":
        bill_ref = _text(root, "cac:BillingReference/cac:InvoiceDocumentReference/cbc:ID", ns)
        if not bill_ref:
            errors.append("PEPPOL-CREDIT-01: CreditNote must reference an Invoice ID (BT-25)")

    # 3. Seller & Buyer parties + BR-CO-09
    sup_party = root.find("cac:AccountingSupplierParty/cac:Party", namespaces=ns)
    cus_party = root.find("cac:AccountingCustomerParty/cac:Party", namespaces=ns)
    sup_name = _text(sup_party, "cac:PartyLegalEntity/cbc:RegistrationName", ns)
    cus_name = _text(cus_party, "cac:PartyLegalEntity/cbc:RegistrationName", ns)
    sup_country = _text(sup_party, "cac:PostalAddress/cac:Country/cbc:IdentificationCode", ns)
    cus_country = _text(cus_party, "cac:PostalAddress/cac:Country/cbc:IdentificationCode", ns)
    if not sup_name:
        errors.append("BR-06: Seller name (BT-27) missing")
    if not cus_name:
        errors.append("BR-07: Buyer name (BT-44) missing")
    if not sup_country or not _ISO2_RE.match(sup_country):
        errors.append(f"BR-09: Seller country invalid: {sup_country!r}")
    if not cus_country or not _ISO2_RE.match(cus_country):
        errors.append(f"BR-11: Buyer country invalid: {cus_country!r}")

    def _party_vat_id(party: etree._Element | None) -> str | None:
        if party is None:
            return None
        for pts in party.findall("cac:PartyTaxScheme", namespaces=ns):
            if _text(pts, "cac:TaxScheme/cbc:ID", ns) == "VAT":
                return _text(pts, "cbc:CompanyID", ns)
        return None

    seller_vat_id = _party_vat_id(sup_party)
    buyer_vat_id = _party_vat_id(cus_party)
    if seller_vat_id is not None and not _VAT_PREFIX_RE.match(seller_vat_id):
        errors.append(f"BR-CO-09: Seller VAT ID {seller_vat_id!r} lacks valid ISO-2 prefix")
    if buyer_vat_id is not None and not _VAT_PREFIX_RE.match(buyer_vat_id):
        errors.append(f"BR-CO-09: Buyer VAT ID {buyer_vat_id!r} lacks valid ISO-2 prefix")

    # 4. Lines (BR-16) and line buckets
    lines = root.findall(f"cac:{line_name}", namespaces=ns)
    if not lines:
        errors.append("BR-16: Document must contain at least one invoice/credit-note line")

    bucket_net: dict[tuple[str, Decimal], Decimal] = defaultdict(Decimal)
    line_ext_sum = Decimal("0.00")

    for idx, line in enumerate(lines, start=1):
        lid = _text(line, "cbc:ID", ns)
        if not lid:
            errors.append(f"BR-21: Line {idx} missing ID")
        qty_el = line.find(f"cbc:{qty_name}", namespaces=ns)
        qty_val = _parse_dec(qty_el.text if qty_el is not None else None)
        if qty_val is None or qty_val <= 0:
            errors.append(f"PEPPOL-QTY-01: Line {lid or idx} quantity must be > 0")
        ext_el = line.find("cbc:LineExtensionAmount", namespaces=ns)
        if ext_el is None or ext_el.get("currencyID") != doc_ccy:
            errors.append(f"BR-DEC-11: Line {lid or idx} LineExtensionAmount missing/bad currency")
            continue
        ext_text = (ext_el.text or "").strip()
        if not _MONEY_2DP_RE.match(ext_text):
            errors.append(f"BR-DEC-11: Line {lid or idx} amount {ext_text!r} not 2 decimals")
        ext_val = _parse_dec(ext_text)
        if ext_val is None or ext_val < 0:
            errors.append(f"BR-24: Line {lid or idx} LineExtensionAmount must be >= 0")
            continue
        line_ext_sum += ext_val

        price_el = line.find("cac:Price/cbc:PriceAmount", namespaces=ns)
        if price_el is None or not _PRICE_RE.match((price_el.text or "").strip()):
            errors.append(f"BR-26: Line {lid or idx} PriceAmount missing or invalid format")

        cat_el = line.find("cac:Item/cac:ClassifiedTaxCategory", namespaces=ns)
        cat_code = _text(cat_el, "cbc:ID", ns)
        rate_val = _parse_dec(_text(cat_el, "cbc:Percent", ns))
        if cat_code not in {"S", "Z", "E", "AE", "K"} or rate_val is None:
            errors.append(f"BR-CO-04: Line {lid or idx} invalid ClassifiedTaxCategory")
            continue
        bucket_net[(cat_code, rate_val)] += ext_val

    # 5. Document-level allowances & charges
    doc_allowance_sum = Decimal("0.00")
    doc_charge_sum = Decimal("0.00")
    for ac in root.findall("cac:AllowanceCharge", namespaces=ns):
        ind = _text(ac, "cbc:ChargeIndicator", ns)
        amt_el = ac.find("cbc:Amount", namespaces=ns)
        if amt_el is None or amt_el.get("currencyID") != doc_ccy:
            errors.append("BR-AC-01: AllowanceCharge Amount missing or wrong currencyID")
            continue
        amt_text = (amt_el.text or "").strip()
        if not _MONEY_2DP_RE.match(amt_text):
            errors.append(f"BR-DEC-04: AllowanceCharge Amount {amt_text!r} not 2 decimals")
        amt_val = _parse_dec(amt_text)
        cat_el = ac.find("cac:TaxCategory", namespaces=ns)
        cat_code = _text(cat_el, "cbc:ID", ns)
        rate_val = _parse_dec(_text(cat_el, "cbc:Percent", ns))
        if amt_val is None or amt_val < 0 or cat_code is None or rate_val is None:
            errors.append("BR-AC-02: Invalid AllowanceCharge values")
            continue
        if ind == "true":
            doc_charge_sum += amt_val
            bucket_net[(cat_code, rate_val)] += amt_val
        elif ind == "false":
            doc_allowance_sum += amt_val
            bucket_net[(cat_code, rate_val)] -= amt_val
        else:
            errors.append(f"BR-AC-03: Invalid ChargeIndicator {ind!r}")

    # 6. TaxTotal & TaxSubtotal checks (BR-53, PEPPOL R053/R054, BR-CO-14, BR-CO-17, BR-CO-18)
    tax_totals = root.findall("cac:TaxTotal", namespaces=ns)
    with_subtotals = [tt for tt in tax_totals if tt.findall("cac:TaxSubtotal", namespaces=ns)]
    without_subtotals = [
        tt for tt in tax_totals if not tt.findall("cac:TaxSubtotal", namespaces=ns)
    ]

    if len(with_subtotals) != 1:
        errors.append(
            f"PEPPOL-EN16931-R053: Expected 1 TaxTotal with TaxSubtotal, got {len(with_subtotals)}"
        )
    if tax_ccy is not None and len(without_subtotals) != 1:
        errors.append("BR-53: TaxCurrencyCode present requires second TaxTotal without subtotals")
    if tax_ccy is None and len(without_subtotals) > 0:
        errors.append("PEPPOL-EN16931-R054: Second TaxTotal forbidden when TaxCurrencyCode absent")

    bt_110 = Decimal("0.00")
    subtotal_sum = Decimal("0.00")
    seen_buckets: dict[tuple[str, Decimal], Decimal] = {}
    category_counts: dict[str, int] = defaultdict(int)

    if with_subtotals:
        primary_tt = with_subtotals[0]
        tt_amt_el = primary_tt.find("cbc:TaxAmount", namespaces=ns)
        if tt_amt_el is None or tt_amt_el.get("currencyID") != doc_ccy:
            errors.append("BR-CO-14: Primary TaxTotal currencyID mismatch")
        else:
            tt_txt = (tt_amt_el.text or "").strip()
            if not _MONEY_2DP_RE.match(tt_txt):
                errors.append(f"BR-DEC-13: Primary TaxAmount {tt_txt!r} not 2 decimals")
            parsed_tt = _parse_dec(tt_txt)
            if parsed_tt is not None:
                bt_110 = parsed_tt

        subtotals = primary_tt.findall("cac:TaxSubtotal", namespaces=ns)
        if not subtotals:
            errors.append("BR-CO-18: At least one TaxSubtotal required")

        for sub in subtotals:
            txbl_el = sub.find("cbc:TaxableAmount", namespaces=ns)
            tx_el = sub.find("cbc:TaxAmount", namespaces=ns)
            if (
                txbl_el is None
                or tx_el is None
                or txbl_el.get("currencyID") != doc_ccy
                or tx_el.get("currencyID") != doc_ccy
            ):
                errors.append("BR-SUB-01: TaxSubtotal amounts missing or currency mismatch")
                continue
            txbl_txt = (txbl_el.text or "").strip()
            tx_txt = (tx_el.text or "").strip()
            if not _MONEY_2DP_RE.match(txbl_txt) or not _MONEY_2DP_RE.match(tx_txt):
                errors.append("BR-DEC-14: TaxSubtotal amounts must have 2 decimals")
            txbl_val = _parse_dec(txbl_txt)
            tx_val = _parse_dec(tx_txt)
            cat_el = sub.find("cac:TaxCategory", namespaces=ns)
            cat_code = _text(cat_el, "cbc:ID", ns)
            rate_val = _parse_dec(_text(cat_el, "cbc:Percent", ns))
            reason_code = _text(cat_el, "cbc:TaxExemptionReasonCode", ns)
            reason_text = _text(cat_el, "cbc:TaxExemptionReason", ns)

            if txbl_val is None or tx_val is None or cat_code is None or rate_val is None:
                errors.append("BR-SUB-02: Malformed TaxSubtotal category or values")
                continue

            expected_tax = round_half_up(txbl_val * rate_val / Decimal("100"), 2)
            if tx_val != expected_tax:
                errors.append(
                    f"BR-CO-17: Subtotal ({cat_code}, {rate_val}) tax {tx_val} != {expected_tax}"
                )
            subtotal_sum += tx_val
            key = (cat_code, rate_val)
            if key in seen_buckets:
                errors.append(f"BR-CO-18: Duplicate TaxSubtotal for bucket {key}")
            seen_buckets[key] = txbl_val
            category_counts[cat_code] += 1

            # Category-specific rules
            if cat_code == "S" and rate_val <= 0:
                errors.append("BR-S-05: Category S rate must be > 0")
            if cat_code in {"Z", "AE", "K", "E"} and rate_val != Decimal("0.00"):
                errors.append(f"BR-{cat_code}-05: Category {cat_code} rate must be 0.00")
            if cat_code in {"AE", "K", "E"} and not (reason_code or reason_text):
                errors.append(
                    f"BR-{cat_code}-10: Category {cat_code} requires exemption reason or code"
                )
            if cat_code == "AE":
                if not (seller_vat_id and buyer_vat_id):
                    errors.append("BR-AE-02: Reverse charge (AE) requires Seller and Buyer VAT IDs")
            if cat_code == "K":
                if not (seller_vat_id and buyer_vat_id):
                    errors.append("BR-IC-02: ICS (K) requires Seller and Buyer VAT IDs")
                if sup_country and cus_country and sup_country == cus_country:
                    errors.append("BR-IC-11: ICS (K) requires different Seller & Buyer countries")

        for cat in ("Z", "AE", "K", "E"):
            if category_counts[cat] > 1:
                errors.append(f"BR-{cat}-01: At most one TaxSubtotal allowed for category {cat}")

        if bt_110 != subtotal_sum:
            errors.append(f"BR-CO-14: TaxTotal {bt_110} != sum(TaxSubtotal) {subtotal_sum}")

        # Exact bucket match between lines+AC and TaxSubtotals
        if set(seen_buckets.keys()) != set(bucket_net.keys()):
            errors.append(
                f"BR-BUCKET-01: Subtotal buckets {sorted(seen_buckets)} "
                f"!= line buckets {sorted(bucket_net)}"
            )
        else:
            for key, net_val in bucket_net.items():
                if seen_buckets[key] != net_val:
                    errors.append(
                        f"BR-S-08/CO-17: Bucket {key} taxable "
                        f"{seen_buckets[key]} != lines {net_val}"
                    )

    if tax_ccy is not None and without_subtotals:
        sec_el = without_subtotals[0].find("cbc:TaxAmount", namespaces=ns)
        if sec_el is None or sec_el.get("currencyID") != tax_ccy:
            errors.append(f"BR-53: Secondary TaxTotal must use currencyID={tax_ccy!r}")
        elif not _MONEY_2DP_RE.match((sec_el.text or "").strip()):
            errors.append("BR-DEC-15: Secondary TaxAmount must have 2 decimals")

    # 7. LegalMonetaryTotal checks (BR-CO-10..BR-CO-16)
    lmt = root.find("cac:LegalMonetaryTotal", namespaces=ns)
    if lmt is None:
        errors.append("BR-LMT-01: LegalMonetaryTotal (BG-22) missing")
        return errors

    def _lmt_dec(tag_name: str, *, required: bool = True) -> Decimal:
        el = lmt.find(f"cbc:{tag_name}", namespaces=ns)
        if el is None:
            if required:
                errors.append(f"BR-LMT-02: Missing LegalMonetaryTotal/{tag_name}")
            return Decimal("0.00")
        if el.get("currencyID") != doc_ccy:
            errors.append(f"BR-LMT-03: {tag_name} currencyID != {doc_ccy}")
        txt = (el.text or "").strip()
        if not _MONEY_2DP_RE.match(txt):
            errors.append(f"BR-DEC-LMT: {tag_name} {txt!r} not 2 decimals")
        val = _parse_dec(txt)
        return val if val is not None else Decimal("0.00")

    bt_106 = _lmt_dec("LineExtensionAmount")
    bt_107 = _lmt_dec("AllowanceTotalAmount", required=False)
    bt_108 = _lmt_dec("ChargeTotalAmount", required=False)
    bt_109 = _lmt_dec("TaxExclusiveAmount")
    bt_112 = _lmt_dec("TaxInclusiveAmount")
    bt_113 = _lmt_dec("PrepaidAmount", required=False)
    bt_114 = _lmt_dec("PayableRoundingAmount", required=False)
    bt_115 = _lmt_dec("PayableAmount")

    if bt_106 != line_ext_sum:
        errors.append(f"BR-CO-10: BT-106 {bt_106} != sum(lines) {line_ext_sum}")
    if bt_107 != doc_allowance_sum:
        errors.append(f"BR-CO-11: BT-107 {bt_107} != sum(allowances) {doc_allowance_sum}")
    if bt_108 != doc_charge_sum:
        errors.append(f"BR-CO-12: BT-108 {bt_108} != sum(charges) {doc_charge_sum}")
    if bt_109 != bt_106 - bt_107 + bt_108:
        errors.append(f"BR-CO-13: BT-109 {bt_109} != {bt_106} - {bt_107} + {bt_108}")
    if bt_112 != bt_109 + bt_110:
        errors.append(f"BR-CO-15: BT-112 {bt_112} != {bt_109} + {bt_110}")
    if bt_115 != bt_112 - bt_113 + bt_114:
        errors.append(f"BR-CO-16: BT-115 {bt_115} != {bt_112} - {bt_113} + {bt_114}")

    if doc_kind == "Invoice" and bt_115 > Decimal("0.00"):
        due_date = _text(root, "cbc:DueDate", ns)
        if not due_date or not _DATE_RE.match(due_date):
            errors.append("BR-CO-25: DueDate mandatory on Invoice when PayableAmount > 0")

    return errors
