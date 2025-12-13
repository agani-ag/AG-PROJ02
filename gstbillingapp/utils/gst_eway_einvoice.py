# E-Way Bill and E-Invoice utility functions

from decimal import Decimal
import hashlib
import json
from datetime import datetime


def generate_eway_bill_data(invoice, transporter_details=None):
    """
    Generate E-Way Bill data structure
    
    Args:
        invoice: Invoice object
        transporter_details: Dict with transporter info
    
    Returns:
        Dict with E-Way Bill data
    """
    invoice_json = json.loads(invoice.invoice_json)
    
    eway_bill_data = {
        # Supply Type
        'supplyType': 'O',  # O=Outward, I=Inward
        'subSupplyType': '1',  # 1=Supply, 2=Import, 3=Export, etc.
        'docType': 'INV',  # INV, CHL, BIL, BOE, CNT
        'docNo': str(invoice.invoice_number),
        'docDate': invoice.invoice_date.strftime('%d/%m/%Y'),
        
        # Seller Details (From Business Profile)
        'fromGstin': invoice.user.userprofile.business_gst,
        'fromTrdName': invoice.user.userprofile.business_title,
        'fromAddr1': invoice.user.userprofile.business_address[:100] if invoice.user.userprofile.business_address else '',
        'fromPlace': '',  # City
        'fromPincode': '',  # Extract from address or separate field
        'fromStateCode': invoice.user.userprofile.business_gst[:2] if invoice.user.userprofile.business_gst else '',
        
        # Buyer Details
        'toGstin': invoice.invoice_customer.customer_gst if invoice.invoice_customer else '',
        'toTrdName': invoice.invoice_customer.customer_name if invoice.invoice_customer else '',
        'toAddr1': invoice.invoice_customer.customer_address[:100] if invoice.invoice_customer and invoice.invoice_customer.customer_address else '',
        'toPlace': '',
        'toPincode': '',
        'toStateCode': invoice.invoice_customer.customer_gst[:2] if invoice.invoice_customer and invoice.invoice_customer.customer_gst else '',
        
        # Product Details
        'productName': '',  # Will be filled from items
        'productDesc': '',
        'hsnCode': '',
        'quantity': 0,
        'qtyUnit': 'NOS',  # NOS, KGS, etc.
        
        # Value Details
        'taxableAmount': float(invoice_json['invoice_total_amt_without_gst']),
        'cgstValue': float(invoice_json['invoice_total_amt_cgst']),
        'sgstValue': float(invoice_json['invoice_total_amt_sgst']),
        'igstValue': float(invoice_json['invoice_total_amt_igst']),
        'cessValue': 0,
        'totInvValue': float(invoice_json['invoice_total_amt_with_gst']),
        
        # Transportation Details
        'transMode': '1',  # 1=Road, 2=Rail, 3=Air, 4=Ship
        'transDistance': '',  # In KM
        'transporterId': '',
        'transporterName': '',
        'transDocNo': '',  # Vehicle Number
        'transDocDate': '',
        'vehicleNo': invoice_json.get('vehicle_number', ''),
        'vehicleType': 'R',  # R=Regular, O=ODC (Over Dimensional Cargo)
    }
    
    # Add transporter details if provided
    if transporter_details:
        eway_bill_data.update({
            'transporterId': transporter_details.get('gstin', ''),
            'transporterName': transporter_details.get('name', ''),
            'transDocNo': transporter_details.get('vehicle_number', ''),
        })
    
    # Aggregate product details
    total_qty = 0
    hsn_codes = []
    for item in invoice_json.get('items', []):
        total_qty += int(item.get('invoice_qty', 0))
        hsn = item.get('invoice_hsn', '')
        if hsn and hsn not in hsn_codes:
            hsn_codes.append(hsn)
    
    eway_bill_data['quantity'] = total_qty
    eway_bill_data['hsnCode'] = hsn_codes[0] if hsn_codes else ''
    
    return eway_bill_data


def validate_eway_bill_data(eway_bill_data):
    """
    Validate E-Way Bill data
    
    Returns:
        Tuple (is_valid, errors)
    """
    errors = []
    
    # Required fields
    required_fields = [
        'fromGstin', 'toGstin', 'docNo', 'docDate',
        'taxableAmount', 'totInvValue'
    ]
    
    for field in required_fields:
        if not eway_bill_data.get(field):
            errors.append(f"Missing required field: {field}")
    
    # Validate invoice value threshold
    # E-Way Bill is mandatory for goods worth > ₹50,000
    if eway_bill_data.get('totInvValue', 0) < 50000:
        errors.append("E-Way Bill not required for invoice value below ₹50,000")
    
    # Validate GSTIN format
    from .gst_calculations import validate_gstin
    
    if eway_bill_data.get('fromGstin') and not validate_gstin(eway_bill_data['fromGstin']):
        errors.append("Invalid Supplier GSTIN")
    
    if eway_bill_data.get('toGstin') and not validate_gstin(eway_bill_data['toGstin']):
        errors.append("Invalid Buyer GSTIN")
    
    return (len(errors) == 0, errors)


def calculate_eway_bill_validity(distance_km, invoice_value):
    """
    Calculate E-Way Bill validity period
    
    Rules:
    - For distance up to 100 km: 1 day
    - For every additional 100 km or part thereof: 1 additional day
    
    Returns:
        Number of days valid
    """
    if distance_km <= 100:
        return 1
    
    # Additional days for every 100 km
    additional_days = (distance_km - 100) // 100
    if (distance_km - 100) % 100 > 0:
        additional_days += 1
    
    return 1 + additional_days


# ================= E-Invoice Functions =============================

def generate_einvoice_irn(invoice_data):
    """
    Generate Invoice Reference Number (IRN) for E-Invoice
    IRN is a 64-character hash
    
    Args:
        invoice_data: Dict with invoice details
    
    Returns:
        64-character IRN hash
    """
    # Create string to hash
    irn_string = (
        f"{invoice_data.get('supplier_gstin')}"
        f"{invoice_data.get('doc_type')}"
        f"{invoice_data.get('doc_number')}"
        f"{invoice_data.get('doc_date')}"
    )
    
    # Generate SHA-256 hash
    irn_hash = hashlib.sha256(irn_string.encode()).hexdigest()
    
    return irn_hash.upper()


def generate_einvoice_json(invoice):
    """
    Generate E-Invoice JSON as per NIC schema
    
    Args:
        invoice: Invoice object
    
    Returns:
        Dict with E-Invoice data
    """
    invoice_json = json.loads(invoice.invoice_json)
    
    # Supplier Details
    supplier_gstin = invoice.user.userprofile.business_gst
    
    # Buyer Details
    buyer_gstin = invoice.invoice_customer.customer_gst if invoice.invoice_customer else ''
    
    einvoice_data = {
        'Version': '1.1',
        'TranDtls': {
            'TaxSch': 'GST',
            'SupTyp': 'B2B' if buyer_gstin else 'B2C',
            'RegRev': 'N',  # Reverse Charge
            'IgstOnIntra': 'N',
        },
        'DocDtls': {
            'Typ': 'INV',
            'No': str(invoice.invoice_number),
            'Dt': invoice.invoice_date.strftime('%d/%m/%Y'),
        },
        'SellerDtls': {
            'Gstin': supplier_gstin,
            'LglNm': invoice.user.userprofile.business_title,
            'Addr1': invoice.user.userprofile.business_address[:100] if invoice.user.userprofile.business_address else '',
            'Loc': '',
            'Pin': '',
            'Stcd': supplier_gstin[:2] if supplier_gstin else '',
        },
        'BuyerDtls': {
            'Gstin': buyer_gstin,
            'LglNm': invoice.invoice_customer.customer_name if invoice.invoice_customer else '',
            'Pos': buyer_gstin[:2] if buyer_gstin else '',
            'Addr1': invoice.invoice_customer.customer_address[:100] if invoice.invoice_customer and invoice.invoice_customer.customer_address else '',
            'Loc': '',
            'Pin': '',
            'Stcd': buyer_gstin[:2] if buyer_gstin else '',
        },
        'ItemList': [],
        'ValDtls': {
            'AssVal': float(invoice_json['invoice_total_amt_without_gst']),
            'CgstVal': float(invoice_json['invoice_total_amt_cgst']),
            'SgstVal': float(invoice_json['invoice_total_amt_sgst']),
            'IgstVal': float(invoice_json['invoice_total_amt_igst']),
            'CesVal': 0,
            'Discount': 0,
            'TotInvVal': float(invoice_json['invoice_total_amt_with_gst']),
        },
    }
    
    # Add items
    for idx, item in enumerate(invoice_json.get('items', []), start=1):
        item_data = {
            'SlNo': str(idx),
            'PrdDesc': item.get('invoice_product', ''),
            'IsServc': 'N',  # N=Goods, Y=Service
            'HsnCd': item.get('invoice_hsn', ''),
            'Qty': float(item.get('invoice_qty', 0)),
            'Unit': 'NOS',
            'UnitPrice': float(item.get('invoice_rate_without_gst', 0)),
            'TotAmt': float(item.get('invoice_amt_without_gst', 0)),
            'Discount': float(item.get('invoice_discount', 0)),
            'AssAmt': float(item.get('invoice_amt_without_gst', 0)),
            'GstRt': float(item.get('invoice_gst_percentage', 0)),
            'CgstAmt': float(item.get('invoice_amt_cgst', 0)),
            'SgstAmt': float(item.get('invoice_amt_sgst', 0)),
            'IgstAmt': float(item.get('invoice_amt_igst', 0)),
            'CesAmt': 0,
            'TotItemVal': float(item.get('invoice_amt_with_gst', 0)),
        }
        einvoice_data['ItemList'].append(item_data)
    
    return einvoice_data


def validate_einvoice_threshold(invoice_value, turnover):
    """
    Check if E-Invoice is mandatory based on turnover
    
    E-Invoice is mandatory for businesses with turnover > ₹5 crore
    (This threshold may change - check latest notification)
    
    Args:
        invoice_value: Invoice total value
        turnover: Annual turnover
    
    Returns:
        Boolean - True if E-Invoice is mandatory
    """
    THRESHOLD = 50000000  # ₹5 crore
    
    return turnover > THRESHOLD


def generate_qr_code_data(invoice, irn):
    """
    Generate QR code data for E-Invoice
    
    Args:
        invoice: Invoice object
        irn: Invoice Reference Number
    
    Returns:
        String data for QR code
    """
    invoice_json = json.loads(invoice.invoice_json)
    
    qr_data = {
        'SupplierGSTIN': invoice.user.userprofile.business_gst,
        'BuyerGSTIN': invoice.invoice_customer.customer_gst if invoice.invoice_customer else '',
        'InvoiceNo': str(invoice.invoice_number),
        'InvoiceDate': invoice.invoice_date.strftime('%d/%m/%Y'),
        'InvoiceValue': float(invoice_json['invoice_total_amt_with_gst']),
        'IRN': irn,
    }
    
    # Convert to pipe-separated string
    qr_string = '|'.join([f"{k}={v}" for k, v in qr_data.items()])
    
    return qr_string


# ================= HSN/SAC Code Helpers =============================

HSN_DESCRIPTIONS = {
    '1001': 'Wheat and meslin',
    '1006': 'Rice',
    '0901': 'Coffee',
    '0902': 'Tea',
    '8471': 'Automatic data processing machines',
    '8517': 'Telephone sets, mobile phones',
    '6109': 'T-shirts, singlets and other vests',
    '6203': 'Men\'s suits, ensembles, jackets',
    '3004': 'Medicaments',
    '8703': 'Motor cars and other motor vehicles',
}


def get_hsn_description(hsn_code):
    """Get description for HSN code"""
    # Check if first 4 digits match
    hsn_4 = hsn_code[:4] if len(hsn_code) >= 4 else hsn_code
    return HSN_DESCRIPTIONS.get(hsn_4, 'General Goods')


def get_default_gst_rate_for_hsn(hsn_code):
    """
    Get default GST rate for HSN code
    Note: This is simplified - actual rates vary
    """
    # This is a simplified mapping
    # In production, maintain a complete HSN-GST rate master
    
    hsn_4 = hsn_code[:4] if len(hsn_code) >= 4 else hsn_code
    
    # Common rates
    rate_mapping = {
        '1001': 0,   # Wheat - Nil
        '1006': 0,   # Rice - Nil
        '0901': 0,   # Coffee - Nil
        '0902': 5,   # Tea - 5%
        '8471': 18,  # Computers - 18%
        '8517': 18,  # Mobile phones - 18%
        '6109': 5,   # T-shirts - 5%
        '6203': 12,  # Garments - 12%
        '3004': 12,  # Medicines - 12%
        '8703': 28,  # Motor vehicles - 28%
    }
    
    return rate_mapping.get(hsn_4, 18)  # Default 18%
