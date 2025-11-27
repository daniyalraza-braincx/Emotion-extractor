function Card({ children, className = '', onClick, ...props }) {
  const baseClass = 'card';
  const classes = onClick ? `${baseClass} card--clickable ${className}` : `${baseClass} ${className}`;
  
  const Component = onClick ? 'button' : 'div';
  
  return (
    <Component className={classes} onClick={onClick} {...props}>
      {children}
    </Component>
  );
}

export default Card;


