# GST utility functions for calculations, validations, and exports

import re
from decimal import Decimal


def validate_gstin(gstin):
    """
    Validate GST Identification Number (GSTIN)
    Format: 15 characters - 2 state code + 10 PAN + 1 entity + 1 default Z + 1 checksum
    Example: 27AAPFU0939F1ZV
    """
    if not gstin or len(gstin) != 15:
        return False
    
    # Pattern: 2 digits + 10 alphanumeric + 1 digit + Z + 1 alphanumeric
    pattern = r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$'
    
    return bool(re.match(pattern, gstin.upper()))


def validate_hsn_code(hsn):
    """
    Validate HSN (Harmonized System of Nomenclature) code
    Can be 4, 6, or 8 digits
    """
    if not hsn:
        return True  # HSN is optional
    
    return bool(re.match(r'^\d{4}$|^\d{6}$|^\d{8}$', str(hsn)))


def calculate_gst_amounts(taxable_amount, gst_rate, is_igst=False):
    """
    Calculate GST amounts (CGST, SGST, or IGST)
    
    Args:
        taxable_amount: Base amount without GST
        gst_rate: GST percentage (e.g., 18 for 18%)
        is_igst: If True, calculate IGST; else CGST+SGST
    
    Returns:
        dict with cgst, sgst, igst, and total amounts
    """
    taxable = Decimal(str(taxable_amount))
    rate = Decimal(str(gst_rate))
    
    total_gst = (taxable * rate / 100).quantize(Decimal('0.01'))
    
    if is_igst:
        return {
            'cgst': Decimal('0'),
            'sgst': Decimal('0'),
            'igst': total_gst,
            'total_with_gst': taxable + total_gst,
        }
    else:
        half_gst = (total_gst / 2).quantize(Decimal('0.01'))
        return {
            'cgst': half_gst,
            'sgst': half_gst,
            'igst': Decimal('0'),
            'total_with_gst': taxable + total_gst,
        }


def calculate_reverse_gst(amount_with_gst, gst_rate):
    """
    Calculate taxable amount from total amount (reverse calculation)
    
    Args:
        amount_with_gst: Total amount including GST
        gst_rate: GST percentage
    
    Returns:
        dict with taxable_amount and gst_amount
    """
    total = Decimal(str(amount_with_gst))
    rate = Decimal(str(gst_rate))
    
    # Formula: Taxable = Total / (1 + Rate/100)
    taxable = (total * 100 / (100 + rate)).quantize(Decimal('0.01'))
    gst_amount = total - taxable
    
    return {
        'taxable_amount': taxable,
        'gst_amount': gst_amount,
    }


def calculate_itc_reversal(itc_claimed, reversal_percentage):
    """
    Calculate ITC reversal amount
    
    Args:
        itc_claimed: Total ITC claimed
        reversal_percentage: Percentage to be reversed
    
    Returns:
        Decimal amount to be reversed
    """
    claimed = Decimal(str(itc_claimed))
    percentage = Decimal(str(reversal_percentage))
    
    return (claimed * percentage / 100).quantize(Decimal('0.01'))


def get_gst_rate_category(gst_rate):
    """
    Categorize GST rate into standard categories
    """
    rate = float(gst_rate)
    
    if rate == 0:
        return 'Nil Rated'
    elif rate == 0.25:
        return '0.25%'
    elif rate == 3:
        return '3%'
    elif rate == 5:
        return '5%'
    elif rate == 12:
        return '12%'
    elif rate == 18:
        return '18%'
    elif rate == 28:
        return '28%'
    else:
        return f'{rate}%'


def extract_state_code_from_gstin(gstin):
    """
    Extract state code from GSTIN (first 2 digits)
    """
    if not gstin or len(gstin) < 2:
        return None
    
    return gstin[:2]


def is_inter_state_supply(supplier_gstin, customer_gstin):
    """
    Determine if supply is inter-state (IGST applicable)
    
    Returns:
        True if inter-state (IGST), False if intra-state (CGST+SGST)
    """
    if not supplier_gstin or not customer_gstin:
        return False
    
    supplier_state = extract_state_code_from_gstin(supplier_gstin)
    customer_state = extract_state_code_from_gstin(customer_gstin)
    
    return supplier_state != customer_state


def get_financial_year(date):
    """
    Get financial year for a given date
    Financial year in India: April to March
    
    Returns:
        String in format "YYYY-YY" (e.g., "2024-25")
    """
    if date.month >= 4:
        return f"{date.year}-{str(date.year + 1)[-2:]}"
    else:
        return f"{date.year - 1}-{str(date.year)[-2:]}"


def get_gst_filing_due_date(month, year, return_type='GSTR1'):
    """
    Get due date for GST filing
    
    Args:
        month: Month of tax period
        year: Year of tax period
        return_type: Type of return (GSTR1, GSTR3B, etc.)
    
    Returns:
        datetime.date object for due date
    """
    from datetime import date
    from calendar import monthrange
    
    # Due dates (simplified - actual dates may vary)
    if return_type == 'GSTR1':
        # 11th of next month
        next_month = month + 1 if month < 12 else 1
        next_year = year if month < 12 else year + 1
        return date(next_year, next_month, 11)
    
    elif return_type == 'GSTR3B':
        # 20th of next month
        next_month = month + 1 if month < 12 else 1
        next_year = year if month < 12 else year + 1
        return date(next_year, next_month, 20)
    
    elif return_type == 'GSTR9':
        # 31st December of next financial year
        if month >= 4:
            return date(year + 1, 12, 31)
        else:
            return date(year, 12, 31)
    
    return None


def format_amount_for_gst_portal(amount):
    """
    Format amount for GST portal JSON (2 decimal places)
    """
    return f"{float(amount):.2f}"


def calculate_late_fee(due_date, filing_date, return_type='GSTR3B'):
    """
    Calculate late fee for delayed GST filing
    
    Args:
        due_date: datetime.date when return was due
        filing_date: datetime.date when return was actually filed
        return_type: Type of return
    
    Returns:
        Late fee amount
    """
    if filing_date <= due_date:
        return 0
    
    days_late = (filing_date - due_date).days
    
    # Late fee for GSTR3B: Rs. 50 per day (Rs. 20 for nil return)
    # Max: Rs. 5000
    if return_type == 'GSTR3B':
        daily_fee = 50  # Rs. 50 per day (CGST + SGST = Rs. 100)
        max_fee = 5000
        
        late_fee = days_late * daily_fee
        return min(late_fee, max_fee)
    
    return 0


def calculate_interest_on_late_payment(tax_amount, days_late):
    """
    Calculate interest on late payment of GST
    Interest rate: 18% per annum
    
    Args:
        tax_amount: Amount of tax paid late
        days_late: Number of days delayed
    
    Returns:
        Interest amount
    """
    if days_late <= 0:
        return 0
    
    annual_rate = Decimal('0.18')  # 18% per annum
    daily_rate = annual_rate / 365
    
    amount = Decimal(str(tax_amount))
    days = Decimal(str(days_late))
    
    interest = (amount * daily_rate * days).quantize(Decimal('0.01'))
    
    return interest


def split_invoice_by_gst_rate(invoice_items):
    """
    Split invoice items by GST rate for GSTR-1 reporting
    
    Args:
        invoice_items: List of invoice items
    
    Returns:
        Dict grouped by GST rate
    """
    grouped = {}
    
    for item in invoice_items:
        gst_rate = item.get('gst_percentage', 0)
        
        if gst_rate not in grouped:
            grouped[gst_rate] = {
                'items': [],
                'total_taxable': Decimal('0'),
                'total_cgst': Decimal('0'),
                'total_sgst': Decimal('0'),
                'total_igst': Decimal('0'),
            }
        
        grouped[gst_rate]['items'].append(item)
        grouped[gst_rate]['total_taxable'] += Decimal(str(item.get('taxable_amount', 0)))
        grouped[gst_rate]['total_cgst'] += Decimal(str(item.get('cgst', 0)))
        grouped[gst_rate]['total_sgst'] += Decimal(str(item.get('sgst', 0)))
        grouped[gst_rate]['total_igst'] += Decimal(str(item.get('igst', 0)))
    
    return grouped


def reconcile_gstr2a_amounts(our_amount, gstr2a_amount, tolerance=0.01):
    """
    Check if amounts match within tolerance
    
    Args:
        our_amount: Amount in our books
        gstr2a_amount: Amount in GSTR-2A
        tolerance: Acceptable difference
    
    Returns:
        Tuple (is_matched, difference)
    """
    our = Decimal(str(our_amount or 0))
    gstr2a = Decimal(str(gstr2a_amount or 0))
    
    difference = abs(our - gstr2a)
    is_matched = difference <= Decimal(str(tolerance))
    
    return (is_matched, float(difference))


# State code to name mapping
GST_STATE_CODES = {
    '01': 'Jammu and Kashmir',
    '02': 'Himachal Pradesh',
    '03': 'Punjab',
    '04': 'Chandigarh',
    '05': 'Uttarakhand',
    '06': 'Haryana',
    '07': 'Delhi',
    '08': 'Rajasthan',
    '09': 'Uttar Pradesh',
    '10': 'Bihar',
    '11': 'Sikkim',
    '12': 'Arunachal Pradesh',
    '13': 'Nagaland',
    '14': 'Manipur',
    '15': 'Mizoram',
    '16': 'Tripura',
    '17': 'Meghalaya',
    '18': 'Assam',
    '19': 'West Bengal',
    '20': 'Jharkhand',
    '21': 'Odisha',
    '22': 'Chhattisgarh',
    '23': 'Madhya Pradesh',
    '24': 'Gujarat',
    '26': 'Dadra and Nagar Haveli and Daman and Diu',
    '27': 'Maharashtra',
    '29': 'Karnataka',
    '30': 'Goa',
    '31': 'Lakshadweep',
    '32': 'Kerala',
    '33': 'Tamil Nadu',
    '34': 'Puducherry',
    '35': 'Andaman and Nicobar Islands',
    '36': 'Telangana',
    '37': 'Andhra Pradesh',
    '38': 'Ladakh',
    '97': 'Other Territory',
}


def get_state_name_from_code(state_code):
    """Get state name from GST state code"""
    return GST_STATE_CODES.get(state_code, 'Unknown')


def get_state_name_from_gstin(gstin):
    """Extract and get state name from GSTIN"""
    state_code = extract_state_code_from_gstin(gstin)
    if state_code:
        return get_state_name_from_code(state_code)
    return None
