# 🚀 Quick Reference Guide - Mobile UI/UX

## 🎨 Color Reference

### Light Mode
```css
Background:     #f5f5f5
Surface:        #ffffff
Text Primary:   #1c1c1e
Text Secondary: #6e6e73
Accent:         #007aff
Success:        #34c759
Danger:         #ff3b30
Warning:        #ff9500
```

### Dark Mode
```css
Background:     #000000
Surface:        #1c1c1e
Text Primary:   #ffffff
Text Secondary: #a1a1a6
Accent:         #007aff
Success:        #34c759
Danger:         #ff3b30
Warning:        #ff9500
```

## 📱 Page Gradients

```css
Profile:  linear-gradient(135deg, #667eea 0%, #764ba2 100%)
Home:     linear-gradient(135deg, #667eea 0%, #764ba2 100%)
Books:    linear-gradient(135deg, #ff3b30 0%, #ff6b6b 100%)
Invoices: linear-gradient(135deg, #5856d6 0%, #7b79e8 100%)
```

## 🔧 JavaScript API

### Haptic Feedback
```javascript
haptic.light();      // 10ms - taps
haptic.medium();     // 20ms - actions  
haptic.heavy();      // 30ms - confirmations
haptic.success();    // pattern - success
haptic.error();      // pattern - error
```

### Theme Management
```javascript
themeManager.init();                    // Initialize
themeManager.setTheme('dark', true);    // Set dark mode
themeManager.setTheme('light', true);   // Set light mode
```

### Pull to Refresh
```javascript
pullToRefresh.init();  // Auto-initializes in base.html
```

## 🎯 CSS Classes

### Loading Skeletons
```html
<div class="skeleton skeleton-text"></div>
<div class="skeleton skeleton-title"></div>
<div class="skeleton skeleton-card"></div>
```

### Empty State
```html
<div class="empty-state">
    <div class="empty-state-icon"><i class="fas fa-icon"></i></div>
    <h3 class="empty-state-title">Title</h3>
    <p class="empty-state-text">Message</p>
</div>
```

### Card Component
```html
<div class="oneui-card">
    <div class="section-header">
        <h3 class="section-title">Title</h3>
    </div>
    <div class="info-item">
        <div class="info-icon"><i class="fas fa-icon"></i></div>
        <div class="info-content">
            <p class="info-label">Label</p>
            <p class="info-value">Value</p>
        </div>
    </div>
</div>
```

## 📏 Spacing Scale

```
XS:  8px   - Tight spacing
SM:  12px  - Compact spacing
MD:  16px  - Standard spacing
LG:  20px  - Comfortable spacing
XL:  24px  - Section spacing
2XL: 32px  - Large gaps
3XL: 40px  - Header spacing
```

## 🎯 Touch Targets

```
Minimum:  44x44px (iOS standard)
Preferred: 48x48px (Material standard)
Buttons:  48-56px height
Icons:    24px (visual), 48px (touch area)
```

## 🌈 Transaction Colors

```css
Payment:  #34c759 (Green)
Purchase: #ff3b30 (Red)
Return:   #ff9500 (Orange)
Advance:  #5856d6 (Purple)
Other:    #007aff (Blue)
Inactive: #a1a1a6 (Gray)
```

## 📝 Typography

```
Page Title:      24-26px / 700
Section Title:   20px / 700
Card Title:      17px / 600
Body:            16px / 500
Secondary:       15px / 500
Label:           13px / 500-600
Caption:         11-12px / 500
```

## ⚡ Animation Timing

```css
Quick:    200ms  - Micro-interactions
Standard: 300ms  - UI transitions
Slow:     500ms  - Page transitions
Easing:   cubic-bezier(0.4, 0, 0.2, 1)
```

## 🎨 Border Radius

```css
Small:    12px
Default:  16px
Large:    20px
Circle:   50%
```

## 📦 Shadows

```css
Default:  0 2px 12px rgba(0, 0, 0, 0.08)
Large:    0 8px 24px rgba(0, 0, 0, 0.12)

Dark Mode:
Default:  0 2px 12px rgba(0, 0, 0, 0.4)
Large:    0 8px 24px rgba(0, 0, 0, 0.6)
```

## 🔤 Font Stack

```css
font-family: -apple-system, BlinkMacSystemFont, 
             'Segoe UI', Roboto, 
             'Helvetica Neue', Arial, 
             sans-serif;
```

## 📱 Responsive Breakpoints

```css
Small Phone:  ≤375px
Standard:     376-768px
Tablet:       769px+
```

## 🎯 Z-Index Scale

```css
Base:           1
Dropdown:       100
Sticky:         1000
Modal:          9000
Navigation:     9999
Theme Toggle:   10000
```

## 💡 Pro Tips

### Always Use Variables
```css
/* Good ✅ */
color: var(--oneui-text-primary);

/* Bad ❌ */
color: #1c1c1e;
```

### Add Haptic to Interactions
```javascript
button.addEventListener('click', () => {
    haptic.light();  // ✅ Good UX
    // your code
});
```

### Show Loading States
```javascript
function loadData() {
    showLoading();        // ✅ Immediate feedback
    fetch(url)
        .then(handleData);
}
```

### Handle Empty States
```javascript
if (data.length === 0) {
    showEmptyState();     // ✅ Guide users
}
```

## 📚 Documentation Files

1. **DESIGN_SYSTEM.md** - Complete design system
2. **ADVANCED_FEATURES.md** - Feature documentation  
3. **IMPLEMENTATION_SUMMARY.md** - Complete summary
4. **QUICK_REFERENCE.md** - This file

## 🚀 Getting Started

### Toggle Dark Mode
- Click moon/sun icon (top-right)
- Theme saves automatically

### Use Pull-to-Refresh
- Scroll to top
- Pull down
- Release to reload

### Search with Loading
- Type in search box
- Loading skeleton appears
- Results load smoothly

### Navigate with Haptic
- Every tap has feedback
- Feels premium and responsive

---

**Quick Reference v2.0** | Last Updated: January 2026
