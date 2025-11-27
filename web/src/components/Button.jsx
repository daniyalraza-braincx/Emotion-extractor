function Button({ 
  children, 
  variant = 'primary', 
  size = 'medium',
  icon,
  iconPosition = 'left',
  className = '',
  disabled = false,
  ...props 
}) {
  const baseClass = 'btn';
  const variantClass = `btn--${variant}`;
  const sizeClass = `btn--${size}`;
  const iconClass = icon ? `btn--icon-${iconPosition}` : '';
  const classes = `${baseClass} ${variantClass} ${sizeClass} ${iconClass} ${className}`.trim();
  
  return (
    <button className={classes} disabled={disabled} {...props}>
      {icon && iconPosition === 'left' && <span className="btn-icon">{icon}</span>}
      {children}
      {icon && iconPosition === 'right' && <span className="btn-icon">{icon}</span>}
    </button>
  );
}

export default Button;


