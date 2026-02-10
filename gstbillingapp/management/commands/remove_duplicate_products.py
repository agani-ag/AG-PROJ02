from django.core.management.base import BaseCommand
from django.db.models import Count, Sum
from django.db import transaction
from gstbillingapp.models import Product, Inventory, InventoryLog


class Command(BaseCommand):
    help = 'Remove duplicate products keeping the most recent one and merging inventory data'

    def handle(self, *args, **options):
        # Find duplicates
        duplicates = Product.objects.values('user', 'model_no').annotate(
            count=Count('id')
        ).filter(count__gt=1)

        total_removed = 0
        total_groups = len(duplicates)
        total_inventory_merged = 0
        total_logs_merged = 0

        self.stdout.write(f"Found {total_groups} groups of duplicate products")

        for dup in duplicates:
            user_id = dup['user']
            model_no = dup['model_no']
            
            # Get all products with same user and model_no
            products = Product.objects.filter(
                user_id=user_id, 
                model_no=model_no
            ).order_by('-id')

            # Keep the first (most recent) and delete the rest
            products_to_delete = list(products[1:])
            keeper = products[0]
            
            self.stdout.write(f"\nProcessing: {model_no} (User: {user_id})")
            self.stdout.write(f"  Keeping Product ID: {keeper.id}")
            
            with transaction.atomic():
                for product in products_to_delete:
                    # Count inventory logs to be merged
                    logs_count = InventoryLog.objects.filter(product=product).count()
                    if logs_count > 0:
                        self.stdout.write(f"  - Merging {logs_count} inventory logs from Product ID: {product.id}")
                        total_logs_merged += logs_count
                    
                    # Update all inventory logs to point to keeper
                    InventoryLog.objects.filter(product=product).update(product=keeper)
                    
                    # Check for inventory record
                    duplicate_inventory = Inventory.objects.filter(product=product).first()
                    if duplicate_inventory:
                        self.stdout.write(f"  - Merging inventory record from Product ID: {product.id}")
                        total_inventory_merged += 1
                        duplicate_inventory.delete()
                    
                    self.stdout.write(f"  - Deleting Product ID: {product.id}")
                    product.delete()
                    total_removed += 1
                
                # Recalculate keeper's inventory from all its logs
                keeper_inventory = Inventory.objects.filter(product=keeper).first()
                if keeper_inventory:
                    # Sum all inventory changes
                    total_stock = InventoryLog.objects.filter(
                        product=keeper
                    ).aggregate(Sum('change'))['change__sum'] or 0
                    
                    # Get the most recent log
                    last_log = InventoryLog.objects.filter(product=keeper).order_by('-id').first()
                    
                    # Update inventory
                    keeper_inventory.current_stock = total_stock
                    keeper_inventory.last_log = last_log
                    keeper_inventory.save()
                    
                    self.stdout.write(f"  ✓ Updated inventory stock: {total_stock}")
                else:
                    # Create inventory if doesn't exist but has logs
                    if InventoryLog.objects.filter(product=keeper).exists():
                        total_stock = InventoryLog.objects.filter(
                            product=keeper
                        ).aggregate(Sum('change'))['change__sum'] or 0
                        last_log = InventoryLog.objects.filter(product=keeper).order_by('-id').first()
                        
                        Inventory.objects.create(
                            user=keeper.user,
                            product=keeper,
                            current_stock=total_stock,
                            alert_level=0,
                            last_log=last_log
                        )
                        self.stdout.write(f"  ✓ Created inventory with stock: {total_stock}")

        self.stdout.write(
            self.style.SUCCESS(
                f'\n{"="*60}\n'
                f'Successfully removed {total_removed} duplicate products from {total_groups} groups\n'
                f'Merged {total_logs_merged} inventory logs\n'
                f'Merged {total_inventory_merged} inventory records\n'
                f'{"="*60}'
            )
        )
