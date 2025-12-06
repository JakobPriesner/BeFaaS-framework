"""
Function call graph plots for BeFaaS analysis.
"""

import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

from .constants import FUNCTION_CALL_GRAPH, AUTH_REQUIRED_FUNCTIONS, FUNCTION_CATEGORIES


def get_function_category(func_name):
    """Get the category of a function"""
    for category, funcs in FUNCTION_CATEGORIES.items():
        if func_name in funcs:
            return category
    return 'other'


def get_all_dependencies(func_name, visited=None):
    """Recursively get all dependencies of a function"""
    if visited is None:
        visited = set()

    if func_name in visited:
        return set()

    visited.add(func_name)
    deps = set()

    direct_deps = FUNCTION_CALL_GRAPH.get(func_name, [])
    for dep in direct_deps:
        deps.add(dep)
        deps.update(get_all_dependencies(dep, visited.copy()))

    return deps


def plot_function_call_graph(func_name, output_path):
    """Create a call graph visualization for a specific function"""
    try:
        import networkx as nx
    except ImportError:
        print(f"  networkx not available, skipping call graph for {func_name}")
        return

    G = nx.DiGraph()
    G.add_node(func_name)

    queue = [func_name]
    visited = set()

    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)

        callees = FUNCTION_CALL_GRAPH.get(current, [])
        for callee in callees:
            G.add_node(callee)
            G.add_edge(current, callee)
            if callee not in visited:
                queue.append(callee)

    if len(G.nodes()) == 0:
        print(f"  No call graph data for {func_name}")
        return

    fig, ax = plt.subplots(figsize=(14, 10))

    try:
        pos = nx.nx_agraph.graphviz_layout(G, prog='dot')
    except:
        pos = nx.spring_layout(G, k=2, iterations=50)

    category_colors = {
        'entry': '#4CAF50',
        'critical': '#FF9800',
        'cart': '#2196F3',
        'product': '#9C27B0',
        'utility': '#607D8B',
        'auth': '#E91E63',
        'other': '#9E9E9E',
    }

    node_colors = []
    node_sizes = []
    edge_colors = []

    for node in G.nodes():
        category = get_function_category(node)
        color = category_colors.get(category, '#9E9E9E')
        node_colors.append(color)

        if node == func_name:
            node_sizes.append(3500)
        elif node in AUTH_REQUIRED_FUNCTIONS:
            node_sizes.append(2500)
        else:
            node_sizes.append(2000)

    for u, v in G.edges():
        if v in AUTH_REQUIRED_FUNCTIONS:
            edge_colors.append('#E91E63')
        else:
            edge_colors.append('#666666')

    nx.draw_networkx_edges(G, pos, edge_color=edge_colors, alpha=0.7, width=2,
                          arrows=True, arrowsize=20, arrowstyle='->', ax=ax,
                          connectionstyle='arc3,rad=0.1')

    nx.draw_networkx_nodes(G, pos, node_color=node_colors, node_size=node_sizes,
                          alpha=0.9, linewidths=2,
                          edgecolors=['#C62828' if n in AUTH_REQUIRED_FUNCTIONS else '#333' for n in G.nodes()],
                          ax=ax)

    nx.draw_networkx_labels(G, pos, font_size=9, font_weight='bold', ax=ax)

    ax.set_title(f'Function Call Graph: {func_name}', fontsize=16, fontweight='bold', pad=20)

    legend_elements = [
        mpatches.Patch(facecolor='#4CAF50', label='Entry Point', alpha=0.9),
        mpatches.Patch(facecolor='#FF9800', label='Critical Path', alpha=0.9),
        mpatches.Patch(facecolor='#2196F3', label='Cart Operations', alpha=0.9),
        mpatches.Patch(facecolor='#9C27B0', label='Product Services', alpha=0.9),
        mpatches.Patch(facecolor='#607D8B', label='Utility Services', alpha=0.9),
        mpatches.Patch(facecolor='#E91E63', label='Auth Services', alpha=0.9),
        mpatches.Patch(facecolor='white', edgecolor='#C62828', label='Auth Required', linewidth=2),
    ]
    ax.legend(handles=legend_elements, loc='upper left', fontsize=9)

    total_deps = len(G.nodes()) - 1
    auth_deps = len([n for n in G.nodes() if n in AUTH_REQUIRED_FUNCTIONS and n != func_name])
    stats_text = f"Dependencies: {total_deps}\nAuth-required: {auth_deps}"
    ax.text(0.98, 0.02, stats_text, transform=ax.transAxes, fontsize=10,
            verticalalignment='bottom', horizontalalignment='right',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

    ax.axis('off')
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"  Saved call graph for {func_name} to {output_path}")
    plt.close()


def generate_callgraph_plots(output_dir):
    """Generate call graph plots for all key functions"""
    print("\n--- Generating Function Call Graph Plots ---")

    key_functions = ['frontend', 'checkout', 'getcart', 'addcartitem', 'emptycart',
                    'listrecommendations', 'payment']

    for func in key_functions:
        if func in FUNCTION_CALL_GRAPH:
            output_path = os.path.join(output_dir, f'callgraph_{func}.png')
            plot_function_call_graph(func, output_path)