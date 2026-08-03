"""Worked diagram examples. Data, not logic — adding a subject means adding
entries here, never another module.

Every example uses the SAME standard market so the model has one consistent set
of numbers to copy:

    D:  P = 10 - 0.8Q        S:  P = 2 + 0.8Q        equilibrium (Q=5, P=6)

That matters. The model reliably copies the curve equations out of an example
but works out the annotations itself, and it got that arithmetic wrong in 15 of
15 generations until the numeric rule in GRAPH_SYSTEM_PROMPT was added. Adding
an example on different curve equations makes that rule a lie.
"""

EXAMPLES = [
    {
        "description": "supply and demand curves for a market, with the "
                       "equilibrium price and quantity marked",
        "code": """q = np.linspace(0, 10, 200)
plt.plot(q, 10 - 0.8 * q, label=r'$D$')
plt.plot(q, 2 + 0.8 * q, label=r'$S$')
plt.plot([5, 5], [0, 6], linestyle='--', color='red', linewidth=1)
plt.plot([0, 5], [6, 6], linestyle='--', color='red', linewidth=1)
plt.scatter([5], [6], color='red', zorder=5, label='Equilibrium')
plt.xlabel(r'$Q$')
plt.ylabel(r'$P$')
plt.title('Market equilibrium')
plt.xlim(0, 10)
plt.ylim(0, 12)
plt.grid(True, alpha=0.3)
plt.legend()
plt.tight_layout()""",
    },
    {
        "description": "a price ceiling or maximum price set below equilibrium, "
                       "showing the shortage it causes",
        "code": """q = np.linspace(0, 10, 200)
plt.plot(q, 10 - 0.8 * q, label=r'$D$')
plt.plot(q, 2 + 0.8 * q, label=r'$S$')
plt.axhline(4, color='red', label='Price ceiling')
plt.plot([2.5, 7.5], [4, 4], color='orange', linewidth=4, label='Shortage')
plt.scatter([2.5, 7.5], [4, 4], color='orange', zorder=5)
plt.xlabel(r'$Q$')
plt.ylabel(r'$P$')
plt.title('Price ceiling')
plt.xlim(0, 10)
plt.ylim(0, 12)
plt.grid(True, alpha=0.3)
plt.legend()
plt.tight_layout()""",
    },
    {
        "description": "a price floor or minimum price set above equilibrium, "
                       "showing the surplus it causes",
        "code": """q = np.linspace(0, 10, 200)
plt.plot(q, 10 - 0.8 * q, label=r'$D$')
plt.plot(q, 2 + 0.8 * q, label=r'$S$')
plt.axhline(8, color='red', label='Price floor')
plt.plot([2.5, 7.5], [8, 8], color='orange', linewidth=4, label='Surplus')
plt.scatter([2.5, 7.5], [8, 8], color='orange', zorder=5)
plt.xlabel(r'$Q$')
plt.ylabel(r'$P$')
plt.title('Price floor')
plt.xlim(0, 10)
plt.ylim(0, 12)
plt.grid(True, alpha=0.3)
plt.legend()
plt.tight_layout()""",
    },
    {
        "description": "an increase in demand shifting the demand curve right, "
                       "with the old and new equilibrium both marked",
        "code": """q = np.linspace(0, 10, 200)
plt.plot(q, 10 - 0.8 * q, label=r'$D$')
plt.plot(q, 12 - 0.8 * q, linestyle='--', label=r'$D_1$')
plt.plot(q, 2 + 0.8 * q, label=r'$S$')
plt.scatter([5], [6], color='grey', zorder=5, label='Old equilibrium')
plt.scatter([6.25], [7], color='red', zorder=5, label='New equilibrium')
plt.xlabel(r'$Q$')
plt.ylabel(r'$P$')
plt.title('Demand shifts right')
plt.xlim(0, 10)
plt.ylim(0, 12)
plt.grid(True, alpha=0.3)
plt.legend()
plt.tight_layout()""",
    },
    {
        "description": "a labour market with a minimum wage set above the "
                       "equilibrium wage, showing the unemployment it causes",
        "code": """l = np.linspace(0, 10, 200)
plt.plot(l, 10 - 0.8 * l, label=r'$D_L$')
plt.plot(l, 2 + 0.8 * l, label=r'$S_L$')
plt.axhline(8, color='red', label='Minimum wage')
plt.plot([2.5, 7.5], [8, 8], color='orange', linewidth=4, label='Unemployment')
plt.scatter([2.5, 7.5], [8, 8], color='orange', zorder=5)
plt.xlabel(r'$L$ (quantity of labour)')
plt.ylabel(r'$W$ (wage)')
plt.title('Minimum wage and unemployment')
plt.xlim(0, 10)
plt.ylim(0, 12)
plt.grid(True, alpha=0.3)
plt.legend()
plt.tight_layout()""",
    },
    {
        "description": "a break-even chart for a business, showing total "
                       "revenue, total costs, fixed costs and the break-even point",
        "code": """q = np.linspace(0, 80, 200)
plt.plot(q, 10 * q, label='Total revenue')
plt.plot(q, 200 + 5 * q, label='Total costs')
plt.axhline(200, color='grey', linestyle=':', label='Fixed costs')
plt.plot([40, 40], [0, 400], linestyle='--', color='red', linewidth=1)
plt.scatter([40], [400], color='red', zorder=5, label='Break-even point')
plt.xlabel('Output (units)')
plt.ylabel('Value')
plt.title('Break-even chart')
plt.xlim(0, 80)
plt.ylim(0, 800)
plt.grid(True, alpha=0.3)
plt.legend()
plt.tight_layout()""",
    },
    {
        "description": "a normal distribution curve with the upper five percent "
                       "tail shaded, for a statistics significance test",
        "code": """x = np.linspace(-4, 4, 400)
y = np.exp(-x ** 2 / 2) / np.sqrt(2 * np.pi)
plt.plot(x, y, label=r'$N(0, 1)$')
plt.fill_between(x, y, where=(x >= 1.645), alpha=0.4, color='red', label='Upper 5%')
plt.axvline(1.645, color='red', linestyle='--', linewidth=1)
plt.xlabel(r'$z$')
plt.ylabel('Density')
plt.title('Standard normal distribution')
plt.grid(True, alpha=0.3)
plt.legend()
plt.tight_layout()""",
    },
]
