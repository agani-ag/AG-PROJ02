# Samsung One UI Design System - GST Billing Mobile App

## Design Philosophy

This mobile interface follows Samsung One UI principles to deliver a premium, production-ready user experience with:

- **Content-First Design**: Key information positioned in the lower half of the screen for comfortable one-handed use
- **Clean Minimalism**: Elegant visual style with soft surfaces and subtle depth
- **Premium Typography**: Modern font stack with careful sizing and spacing
- **Smooth Interactions**: Subtle micro-interactions and transitions for enhanced user delight

## Color Palette

### Primary Colors
```css
--oneui-primary: #0078d4;    /* Primary blue */
--oneui-accent: #007aff;      /* Interactive accent */
```

### Semantic Colors
```css
--oneui-success: #34c759;     /* Success states, positive actions */
--oneui-danger: #ff3b30;      /* Errors, destructive actions */
--oneui-warning: #ff9500;     /* Warnings, attention needed */
```

### Neutral Colors
```css
--oneui-bg: #f5f5f5;                    /* Background */
--oneui-surface: #ffffff;               /* Card/surface background */
--oneui-text-primary: #1c1c1e;         /* Primary text */
--oneui-text-secondary: #6e6e73;       /* Secondary text */
--oneui-divider: #e5e5ea;              /* Dividers and borders */
```

## Typography

### Font Stack
```css
font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 
             'Helvetica Neue', Arial, sans-serif;
```

### Text Sizes
- **Large Titles**: 26px / 700 weight (Page headers)
- **Title 1**: 24px / 700 weight (Section headers)
- **Title 2**: 20px / 700 weight (Subsections)
- **Headline**: 17px / 600 weight (Card titles)
- **Body**: 16px / 500 weight (Primary content)
- **Callout**: 15px / 500 weight (Secondary content)
- **Subhead**: 13px / 500-600 weight (Labels)
- **Caption**: 11-12px / 500 weight (Captions, badges)

### Letter Spacing
- Large text (≥20px): -0.3 to -0.5px for tighter, cleaner look
- Body text: 0px (default)
- Small caps/labels: +0.5px for better readability

## Layout & Spacing

### Container
```css
max-width: 640px;           /* Optimal reading width */
margin: 0 auto;             /* Center content */
padding-bottom: 80px;       /* Bottom nav clearance */
```

### Padding Scale
- **XS**: 8px
- **SM**: 12px
- **MD**: 16px
- **LG**: 20px
- **XL**: 24px
- **2XL**: 32px
- **3XL**: 40px

### Border Radius
```css
--oneui-radius: 16px;       /* Cards, containers */
--oneui-radius-sm: 12px;    /* Smaller elements */
```

### Shadows
```css
--oneui-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);        /* Default cards */
--oneui-shadow-lg: 0 8px 24px rgba(0, 0, 0, 0.12);     /* Elevated elements */
```

## Components

### Card Component
```css
.oneui-card {
    background: var(--oneui-surface);
    border-radius: var(--oneui-radius);
    box-shadow: var(--oneui-shadow);
    margin-bottom: 16px;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}
```

**Usage**: Primary container for grouped content
- No harsh borders
- Soft shadow for subtle depth
- Smooth transitions on interaction

### Info Item (List Item)
```css
.info-item {
    padding: 16px 20px;
    display: flex;
    align-items: center;
    min-height: 64px;              /* Touch-friendly height */
}
```

**Structure**:
- Icon (40x40px rounded container)
- Label (13px secondary text)
- Value (16px primary text)

### Stat Card
```css
.stat-card {
    background: white;
    border-radius: 16px;
    padding: 20px;
    box-shadow: var(--oneui-shadow);
}
```

**Features**:
- Color-coded left accent border
- Icon with transparent background
- Large value display (22px)
- Secondary count/metric

## Navigation

### Bottom Navigation Bar
```css
.mobile-bottom-nav {
    position: fixed;
    bottom: 0;
    height: 60px;
    background: rgba(255, 255, 255, 0.95);
    backdrop-filter: blur(20px);
}
```

**Nav Items**:
- Icon: 22px
- Label: 11px / 500 weight
- Spacing: 16px horizontal padding
- Active state: Blue accent color (#007aff)
- Active indicator: 3px bottom border

**Touch Targets**: Minimum 48x48px for accessibility

## Page Patterns

### Profile Header
- Gradient background (purple gradient)
- Large avatar (88px diameter)
- Name (24px / 700)
- ID badge with glass morphism effect
- Negative margin to integrate with background

### Section Header
- Title (20px / 700)
- Subtitle (13px / secondary color)
- Generous top padding (24px)

### Welcome Header
- Gradient background
- Greeting text (15px)
- Large customer name (26px / 700)
- Rounded bottom corners

## Interactions & Animations

### Transitions
```css
transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
```

### Active States
```css
:active {
    transform: scale(0.98);      /* Subtle press effect */
    opacity: 0.6;                /* Touch feedback */
}
```

### Micro-interactions
- Cards scale down slightly on press
- Icons move up 2px when nav item is active
- Smooth color transitions on state changes

## Alerts & Messages

### Alert Styling
```css
.alert {
    padding: 16px 20px;
    border-radius: 12px;
    border: none;
    box-shadow: var(--oneui-shadow);
}
```

**Color Variants**:
- Success: Light green background (#e8f5e9) with dark green text
- Danger: Light red background (#ffebee) with dark red text
- Warning: Light orange background (#fff3e0) with dark orange text
- Info: Light blue background (#e3f2fd) with dark blue text

## Accessibility

### Touch Targets
- Minimum 48x48px for all interactive elements
- 44x44px absolute minimum (iOS guidelines)

### Contrast Ratios
- Primary text: 4.5:1 minimum
- Secondary text: 3:1 minimum
- Large text (≥18px): 3:1 minimum

### Font Sizes
- Body text: Minimum 15px
- Labels: Minimum 13px
- Never below 11px

## Responsive Behavior

### Breakpoints
- Small phones: ≤375px
- Standard phones: 376px - 768px
- Tablets: 769px+

### Small Phone Adjustments
```css
@media (max-width: 375px) {
    .profile-header { padding: 32px 16px 50px; }
    .profile-avatar { width: 76px; height: 76px; }
    .profile-name { font-size: 22px; }
}
```

## Best Practices

### Do's
✓ Use consistent spacing (8px grid)
✓ Maintain touch-friendly sizes (min 48px)
✓ Apply subtle shadows for depth
✓ Use smooth, purposeful animations
✓ Keep one-handed usability in mind
✓ Position key content in lower screen half
✓ Use semantic colors consistently
✓ Provide clear visual feedback

### Don'ts
✗ Avoid harsh borders
✗ Don't use aggressive animations
✗ Avoid small touch targets (<44px)
✗ Don't use overly bright colors
✗ Avoid inconsistent spacing
✗ Don't place critical actions at screen top
✗ Avoid poor contrast ratios
✗ Don't skip loading/transition states

## Implementation Notes

### Font Smoothing
```css
-webkit-font-smoothing: antialiased;
-moz-osx-font-smoothing: grayscale;
```

### Backdrop Filter Support
```css
backdrop-filter: blur(20px);
-webkit-backdrop-filter: blur(20px);
```

### Hardware Acceleration
```css
transform: translateZ(0);    /* Enable GPU acceleration */
will-change: transform;      /* Hint browser about changes */
```

## File Structure

```
mobile_v1/
├── base.html                    # Base template with global styles
├── navbarC.html                 # Customer navigation bar
├── customer/
│   ├── customer.html            # Profile page (Samsung One UI)
│   ├── home.html                # Dashboard (Samsung One UI)
│   ├── invoices.html
│   └── books.html
```

## Design Tokens (CSS Variables)

All design tokens are defined in [base.html](gstbillingapp/templates/mobile_v1/base.html) within the `:root` selector for easy customization and theming.

## Credits

Design system inspired by Samsung One UI with adaptations for web-based mobile applications.

---

**Last Updated**: January 2026  
**Version**: 1.0  
**Maintainer**: Frontend Team
