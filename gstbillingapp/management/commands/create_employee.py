"""
Management command to create employees for mobile app access
Usage: python manage.py create_employee
"""

from django.core.management.base import BaseCommand
from django.contrib.auth.hashers import make_password
from gstbillingapp.models import Employee, UserProfile


class Command(BaseCommand):
    help = 'Create a new employee for mobile app access'

    def add_arguments(self, parser):
        parser.add_argument('--username', type=str, help='Business owner username')
        parser.add_argument('--name', type=str, help='Employee name')
        parser.add_argument('--phone', type=str, help='Employee phone number')
        parser.add_argument('--userid', type=str, help='Employee user ID (e.g., EMP001)')
        parser.add_argument('--password', type=str, help='Employee password')
        parser.add_argument('--role', type=str, default='sales', 
                          choices=['admin', 'manager', 'accountant', 'sales', 'inventory', 'cashier'],
                          help='Employee role')
        parser.add_argument('--email', type=str, help='Employee email (optional)')

    def handle(self, *args, **options):
        # Interactive mode if no arguments provided
        if not options['username']:
            options['username'] = input('Enter business owner username: ')
        
        try:
            user_profile = UserProfile.objects.get(user__username=options['username'])
        except UserProfile.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'UserProfile not found for username: {options["username"]}'))
            return
        
        if not options['name']:
            options['name'] = input('Enter employee name: ')
        
        if not options['phone']:
            options['phone'] = input('Enter employee phone: ')
        
        if not options['userid']:
            # Suggest next employee ID
            last_emp = Employee.objects.filter(user_profile=user_profile).order_by('-id').first()
            if last_emp:
                last_num = int(last_emp.employee_userid.replace('EMP', '').replace('emp', ''))
                suggested_id = f'EMP{last_num + 1:03d}'
            else:
                suggested_id = 'EMP001'
            options['userid'] = input(f'Enter employee user ID (suggested: {suggested_id}): ') or suggested_id
        
        if not options['password']:
            from getpass import getpass
            options['password'] = getpass('Enter employee password: ')
            password_confirm = getpass('Confirm password: ')
            if options['password'] != password_confirm:
                self.stdout.write(self.style.ERROR('Passwords do not match!'))
                return
        
        if not options['role']:
            self.stdout.write(self.style.WARNING('\nAvailable roles:'))
            self.stdout.write('1. admin - Full access')
            self.stdout.write('2. manager - Most operations')
            self.stdout.write('3. accountant - Financial operations')
            self.stdout.write('4. sales - Sales and customers')
            self.stdout.write('5. inventory - Inventory management')
            self.stdout.write('6. cashier - Billing only')
            role_choice = input('Select role (1-6): ')
            role_map = {
                '1': 'admin', '2': 'manager', '3': 'accountant',
                '4': 'sales', '5': 'inventory', '6': 'cashier'
            }
            options['role'] = role_map.get(role_choice, 'sales')
        
        # Set permissions based on role
        permissions = {
            'admin': {
                'can_create_invoice': True,
                'can_delete_invoice': True,
                'can_view_reports': True,
                'can_manage_inventory': True,
                'can_manage_customers': True,
            },
            'manager': {
                'can_create_invoice': True,
                'can_delete_invoice': True,
                'can_view_reports': True,
                'can_manage_inventory': True,
                'can_manage_customers': True,
            },
            'accountant': {
                'can_create_invoice': True,
                'can_delete_invoice': False,
                'can_view_reports': True,
                'can_manage_inventory': False,
                'can_manage_customers': False,
            },
            'sales': {
                'can_create_invoice': True,
                'can_delete_invoice': False,
                'can_view_reports': False,
                'can_manage_inventory': False,
                'can_manage_customers': True,
            },
            'inventory': {
                'can_create_invoice': False,
                'can_delete_invoice': False,
                'can_view_reports': False,
                'can_manage_inventory': True,
                'can_manage_customers': False,
            },
            'cashier': {
                'can_create_invoice': True,
                'can_delete_invoice': False,
                'can_view_reports': False,
                'can_manage_inventory': False,
                'can_manage_customers': False,
            },
        }
        
        role_perms = permissions.get(options['role'], permissions['sales'])
        
        # Check if employee userid already exists
        if Employee.objects.filter(employee_userid=options['userid'].lower()).exists():
            self.stdout.write(self.style.ERROR(f'Employee with userid {options["userid"]} already exists!'))
            return
        
        # Create employee
        try:
            employee = Employee.objects.create(
                user_profile=user_profile,
                employee_name=options['name'],
                employee_phone=options['phone'],
                employee_email=options.get('email', ''),
                employee_userid=options['userid'].lower(),
                employee_password=make_password(options['password']),
                role=options['role'],
                **role_perms
            )
            
            self.stdout.write(self.style.SUCCESS(f'\n✓ Employee created successfully!'))
            self.stdout.write(f'Name: {employee.employee_name}')
            self.stdout.write(f'User ID: {employee.employee_userid}')
            self.stdout.write(f'Role: {employee.get_role_display()}')
            self.stdout.write(f'Phone: {employee.employee_phone}')
            self.stdout.write(f'\nPermissions:')
            self.stdout.write(f'  • Create Invoice: {employee.can_create_invoice}')
            self.stdout.write(f'  • Delete Invoice: {employee.can_delete_invoice}')
            self.stdout.write(f'  • View Reports: {employee.can_view_reports}')
            self.stdout.write(f'  • Manage Inventory: {employee.can_manage_inventory}')
            self.stdout.write(f'  • Manage Customers: {employee.can_manage_customers}')
            self.stdout.write(f'\n{self.style.SUCCESS("Employee can now login at:")} /mobile/employee/login')
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error creating employee: {str(e)}'))
