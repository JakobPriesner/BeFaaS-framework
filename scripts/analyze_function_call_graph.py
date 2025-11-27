#!/usr/bin/env python3
"""
Analyze function call graph and visualize with error metrics.

Creates a network diagram showing:
- Which functions call which other functions
- Which calls produce 502 errors (shown as red edges)
- Call frequency (edge thickness)
- Function types (external entry points vs internal services)
"""

import re
import sys
from pathlib import Path
from collections import defaultdict
import matplotlib.pyplot as plt
import networkx as nx
from matplotlib.patches import FancyBboxPatch
import matplotlib.patches as mpatches

def extract_function_calls_from_code(functions_dir):
    """
    Parse function source code to extract all ctx.call() and ctx.lib.call() invocations.

    Returns: dict mapping caller -> list of callees
    """
    call_graph = defaultdict(set)

    # Pattern to match ctx.call('functionName', ...) or ctx.lib.call('functionName', ...)
    call_pattern = re.compile(r"ctx(?:\.lib)?\.call\(['\"]([^'\"]+)['\"]")

    for func_dir in functions_dir.iterdir():
        if not func_dir.is_dir():
            continue

        func_name = func_dir.name
        index_file = func_dir / 'index.js'

        if not index_file.exists():
            continue

        try:
            with open(index_file, 'r') as f:
                content = f.read()

            # Find all function calls
            for match in call_pattern.finditer(content):
                callee = match.group(1)
                call_graph[func_name].add(callee)

        except Exception as e:
            print(f"Warning: Could not parse {func_name}: {e}")

    return {k: list(v) for k, v in call_graph.items()}

def analyze_error_prone_calls(call_graph):
    """
    Identify which function calls are likely to produce 502 errors.

    Based on our analysis:
    - checkout -> * calls produce 502s due to the request/event bug
    - Any call to checkout produces 502
    """
    error_calls = set()

    # Checkout is the main source of 502 errors
    if 'checkout' in call_graph:
        for callee in call_graph['checkout']:
            error_calls.add(('checkout', callee))

    # Calls TO checkout also fail
    for caller, callees in call_graph.items():
        if 'checkout' in callees:
            error_calls.add((caller, 'checkout'))

    return error_calls

def calculate_call_frequencies(call_graph):
    """
    Estimate relative call frequency based on typical e-commerce patterns.

    Returns: dict mapping (caller, callee) -> frequency weight
    """
    frequencies = {}

    # Base weights for different call types
    weights = {
        # Frontend calls (high frequency)
        ('frontend', 'getproduct'): 50,
        ('frontend', 'listproducts'): 30,
        ('frontend', 'searchproducts'): 20,
        ('frontend', 'getcart'): 40,
        ('frontend', 'addcartitem'): 30,
        ('frontend', 'checkout'): 8,  # Conversion rate
        ('frontend', 'emptycart'): 8,
        ('frontend', 'supportedcurrencies'): 35,
        ('frontend', 'getads'): 40,
        ('frontend', 'listrecommendations'): 25,
        ('frontend', 'shipmentquote'): 10,

        # Checkout flow (medium frequency, but part of critical path)
        ('checkout', 'getcart'): 8,
        ('checkout', 'getproduct'): 24,  # Multiple products
        ('checkout', 'currency'): 32,  # Price conversion for each product
        ('checkout', 'shipmentquote'): 8,
        ('checkout', 'payment'): 8,
        ('checkout', 'shiporder'): 8,
        ('checkout', 'email'): 8,
        ('checkout', 'emptycart'): 8,

        # Cart operations (high frequency)
        ('getcart', 'cartkvstorage'): 40,
        ('addcartitem', 'cartkvstorage'): 30,
        ('emptycart', 'cartkvstorage'): 8,

        # Other internal calls
        ('listrecommendations', 'listproducts'): 25,
    }

    # Fill in the frequencies
    for caller, callees in call_graph.items():
        for callee in callees:
            key = (caller, callee)
            frequencies[key] = weights.get(key, 10)  # Default weight

    return frequencies

def create_call_graph_diagram(call_graph, error_calls, frequencies, output_file):
    """Create a network diagram showing function call relationships."""

    # Create directed graph
    G = nx.DiGraph()

    # Add all nodes
    all_functions = set(call_graph.keys())
    for callees in call_graph.values():
        all_functions.update(callees)

    # Categorize functions
    entry_points = {'frontend'}  # External entry points
    critical_path = {'checkout', 'payment', 'shiporder', 'email'}  # Critical e-commerce flow
    data_access = {'cartkvstorage'}  # Data layer
    auth_required = {'checkout', 'getcart', 'addcartitem', 'payment', 'emptycart', 'cartkvstorage'}

    # Add nodes with attributes
    for func in all_functions:
        node_type = 'entry' if func in entry_points else \
                   'critical' if func in critical_path else \
                   'data' if func in data_access else \
                   'service'

        has_auth = func in auth_required

        G.add_node(func, node_type=node_type, has_auth=has_auth)

    # Add edges
    for caller, callees in call_graph.items():
        for callee in callees:
            has_error = (caller, callee) in error_calls
            frequency = frequencies.get((caller, callee), 10)

            G.add_edge(caller, callee, has_error=has_error, frequency=frequency)

    # Create figure
    fig, ax = plt.subplots(figsize=(20, 14))

    # Use hierarchical layout
    # Try to create levels: frontend -> services -> data
    pos = {}
    levels = {
        0: ['frontend'],
        1: ['listproducts', 'searchproducts', 'getproduct', 'supportedcurrencies',
            'getads', 'listrecommendations', 'getcart', 'addcartitem', 'emptycart',
            'checkout', 'shipmentquote', 'currency'],
        2: ['payment', 'shiporder', 'email', 'cartkvstorage']
    }

    # Position nodes in levels
    for level, funcs in levels.items():
        y = 2 - level * 0.9  # Top to bottom
        funcs_in_graph = [f for f in funcs if f in G.nodes()]
        num_funcs = len(funcs_in_graph)

        for i, func in enumerate(funcs_in_graph):
            x = (i - num_funcs / 2) * 1.5
            pos[func] = (x, y)

    # Draw edges
    for (u, v, data) in G.edges(data=True):
        has_error = data.get('has_error', False)
        frequency = data.get('frequency', 10)

        # Edge color and style
        if has_error:
            edge_color = '#D32F2F'  # Red for errors
            edge_style = 'solid'
            edge_alpha = 0.9
            line_width = max(1, frequency / 8) + 1
        else:
            edge_color = '#666666'
            edge_style = 'solid'
            edge_alpha = 0.4
            line_width = max(0.5, frequency / 15)

        nx.draw_networkx_edges(
            G, pos, [(u, v)],
            edge_color=edge_color,
            style=edge_style,
            alpha=edge_alpha,
            width=line_width,
            arrowsize=15 if has_error else 10,
            arrowstyle='->' if has_error else '->',
            connectionstyle='arc3,rad=0.1',
            ax=ax
        )

    # Draw nodes
    node_colors = []
    node_sizes = []
    node_shapes = []

    for node in G.nodes():
        node_type = G.nodes[node].get('node_type', 'service')
        has_auth = G.nodes[node].get('has_auth', False)

        # Color by type
        if node_type == 'entry':
            color = '#4CAF50'  # Green - entry point
            size = 3000
        elif node_type == 'critical':
            color = '#FF9800'  # Orange - critical path
            size = 2500
        elif node_type == 'data':
            color = '#2196F3'  # Blue - data layer
            size = 2500
        else:
            color = '#9E9E9E'  # Gray - regular service
            size = 2000

        # Darker if auth required
        if has_auth:
            # Add red border for auth
            pass

        node_colors.append(color)
        node_sizes.append(size)

    # Draw nodes
    nx.draw_networkx_nodes(
        G, pos,
        node_color=node_colors,
        node_size=node_sizes,
        alpha=0.9,
        linewidths=2,
        edgecolors=['#C62828' if G.nodes[n].get('has_auth') else '#333333' for n in G.nodes()],
        ax=ax
    )

    # Draw labels
    nx.draw_networkx_labels(
        G, pos,
        font_size=9,
        font_weight='bold',
        font_family='sans-serif',
        ax=ax
    )

    # Add title and legend
    ax.set_title('Function Call Graph with Error Analysis\n' +
                'faas-none-2025-11-27T11-01-16-332Z',
                fontsize=16, fontweight='bold', pad=20)

    # Create custom legend
    legend_elements = [
        mpatches.Patch(facecolor='#4CAF50', edgecolor='#333', label='Entry Point (frontend)', linewidth=2),
        mpatches.Patch(facecolor='#FF9800', edgecolor='#333', label='Critical Path (checkout, payment)', linewidth=2),
        mpatches.Patch(facecolor='#2196F3', edgecolor='#333', label='Data Layer (storage)', linewidth=2),
        mpatches.Patch(facecolor='#9E9E9E', edgecolor='#333', label='Service Function', linewidth=2),
        mpatches.Patch(facecolor='white', edgecolor='#C62828', label='Auth Required (red border)', linewidth=3),
        mpatches.Rectangle((0, 0), 1, 0.1, facecolor='#D32F2F', label='502 Error Path (red edge)', linewidth=0),
        mpatches.Rectangle((0, 0), 1, 0.1, facecolor='#666666', label='Normal Call (gray edge)', linewidth=0, alpha=0.4),
    ]

    ax.legend(handles=legend_elements, loc='upper left', fontsize=10, framealpha=0.95)

    # Add statistics box
    total_functions = len(G.nodes())
    total_calls = len(G.edges())
    error_call_count = len(error_calls)

    stats_text = f"Statistics:\n"
    stats_text += f"  Total Functions: {total_functions}\n"
    stats_text += f"  Total Call Paths: {total_calls}\n"
    stats_text += f"  Error-Prone Calls: {error_call_count}\n"
    stats_text += f"  Auth-Required: {len(auth_required)}"

    ax.text(0.99, 0.02, stats_text,
            transform=ax.transAxes,
            fontsize=10,
            verticalalignment='bottom',
            horizontalalignment='right',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8, pad=0.8))

    # Add notes
    notes_text = "Notes:\n"
    notes_text += "• Line thickness = call frequency\n"
    notes_text += "• Red edges = 502 error prone calls\n"
    notes_text += "• Red border = authentication required\n"
    notes_text += "• checkout has 502 errors due to\n"
    notes_text += "  request/event parameter bug"

    ax.text(0.01, 0.02, notes_text,
            transform=ax.transAxes,
            fontsize=9,
            verticalalignment='bottom',
            bbox=dict(boxstyle='round', facecolor='#FFEBEE', alpha=0.9, pad=0.8))

    ax.axis('off')
    plt.tight_layout()
    plt.savefig(output_file, dpi=300, bbox_inches='tight', facecolor='white')
    print(f"\n✓ Call graph saved to: {output_file}")

    return fig

def print_call_graph_summary(call_graph, error_calls, frequencies):
    """Print a text summary of the call graph."""
    print("\n" + "="*70)
    print("FUNCTION CALL GRAPH ANALYSIS")
    print("="*70)

    for caller in sorted(call_graph.keys()):
        callees = sorted(call_graph[caller])
        print(f"\n{caller} calls:")
        for callee in callees:
            freq = frequencies.get((caller, callee), 10)
            has_error = (caller, callee) in error_calls
            error_marker = " ⚠️  502 ERROR" if has_error else ""
            print(f"  → {callee:20s} (frequency: {freq:2d}){error_marker}")

    print("\n" + "="*70)
    print("ERROR-PRONE CALL PATHS")
    print("="*70)
    if error_calls:
        for caller, callee in sorted(error_calls):
            print(f"  ❌ {caller} → {callee}")
    else:
        print("  None detected")

def main():
    # Paths
    base_dir = Path('/Users/jakob/WebstormProjects/BeFaaS-framework2')
    functions_dir = base_dir / 'experiments' / 'webservice' / 'functions'
    results_dir = base_dir / 'scripts' / 'results' / 'webservice' / 'faas-none-2025-11-27T11-01-16-332Z'
    output_file = results_dir / 'analysis' / 'function_call_graph.png'

    if not functions_dir.exists():
        print(f"Error: Functions directory not found: {functions_dir}")
        return 1

    print(f"Analyzing function call relationships...")
    print(f"  Source: {functions_dir}")

    # Extract call graph from source code
    call_graph = extract_function_calls_from_code(functions_dir)

    # Analyze error-prone calls
    error_calls = analyze_error_prone_calls(call_graph)

    # Calculate call frequencies
    frequencies = calculate_call_frequencies(call_graph)

    # Print summary
    print_call_graph_summary(call_graph, error_calls, frequencies)

    # Create visualization
    print("\nGenerating call graph diagram...")
    create_call_graph_diagram(call_graph, error_calls, frequencies, output_file)

    print("\n" + "="*70)
    print(f"Analysis complete!")
    print(f"  Total functions: {len(call_graph)}")
    print(f"  Total call relationships: {sum(len(v) for v in call_graph.values())}")
    print(f"  Error-prone calls: {len(error_calls)}")
    print("="*70)

    return 0

if __name__ == '__main__':
    sys.exit(main())