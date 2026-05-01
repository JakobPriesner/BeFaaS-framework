#!/usr/bin/env python3
"""
Generate BeFaaS Webservice Experiment Infrastructure Diagram.
Professional AWS-style architecture diagram showing all three architecture options.
"""

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Circle
import numpy as np

# ── Color Palette (AWS-inspired) ──────────────────────────────────────────
C = {
    'bg':           '#FFFFFF',
    'vpc_bg':       '#E8F5E9',
    'vpc_border':   '#2E7D32',
    'pub_subnet':   '#FFF3E0',
    'pub_border':   '#E65100',
    'text_dark':    '#1A1A1A',
    'text_mid':     '#424242',
    'text_light':   '#666666',
    'text_muted':   '#999999',
    'arrow':        '#37474F',
    'arrow_light':  '#90A4AE',
    'grid':         '#F5F5F5',
    # AWS service colors
    'lambda':       '#FF9900',
    'lambda_bg':    '#FFF8E8',
    'ecs':          '#FF9900',
    'apigw':        '#A166FF',
    'apigw_bg':     '#F3EAFF',
    'alb':          '#8C4FFF',
    'alb_bg':       '#F0E6FF',
    'cloudfront':   '#8C4FFF',
    'redis':        '#C62828',
    'redis_bg':     '#FFEBEE',
    'cognito':      '#DD344C',
    'cognito_bg':   '#FFF0F1',
    's3':           '#3F8624',
    's3_bg':        '#EDF7EA',
    'cw':           '#E7157B',
    'cw_bg':        '#FFF0F6',
    'igw':          '#8C4FFF',
    'nat':          '#8C4FFF',
    'cloudmap':     '#00897B',
    'cloudmap_bg':  '#E0F2F1',
    'artillery':    '#37474F',
    'artillery_bg': '#ECEFF1',
    # Architecture colors
    'faas':         '#FF9900',
    'faas_bg':      '#FFFBF0',
    'micro':        '#1565C0',
    'micro_bg':     '#F0F7FF',
    'mono':         '#2E7D32',
    'mono_bg':      '#F1F8F1',
    'shared':       '#7B1FA2',
    'shared_bg':    '#FBF3FF',
    'auth':         '#C62828',
    'auth_bg':      '#FFF5F5',
    'obs':          '#37474F',
    'obs_bg':       '#F5F7F8',
}


def create_figure():
    fig = plt.figure(figsize=(32, 24), dpi=200, facecolor=C['bg'])
    ax = fig.add_axes([0.01, 0.01, 0.98, 0.98])
    ax.set_xlim(0, 160)
    ax.set_ylim(0, 120)
    ax.axis('off')
    ax.set_facecolor(C['bg'])
    return fig, ax


def rrect(ax, x, y, w, h, fc, ec, alpha=0.3, lw=2, rad=0.4, zorder=1, ls='-'):
    r = FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={rad}",
                        facecolor=fc, edgecolor=ec, linewidth=lw, alpha=alpha,
                        zorder=zorder, linestyle=ls)
    ax.add_patch(r)
    return r


def service_icon(ax, cx, cy, abbrev, color, size=1.8, zorder=8):
    """Draw an AWS-style service icon: colored circle with abbreviation."""
    circle = Circle((cx, cy), size, facecolor=color, edgecolor='white',
                    linewidth=1.5, alpha=0.95, zorder=zorder)
    ax.add_patch(circle)
    ax.text(cx, cy, abbrev, fontsize=6.5, fontweight='bold', ha='center',
            va='center', color='white', zorder=zorder+1)


def svc_box(ax, x, y, w, h, label, sublabel, icon_abbrev, icon_color,
            bg_color='white', border_color=None, fontsize=7.5, zorder=6):
    """Service component box with icon, label, and sublabel."""
    if border_color is None:
        border_color = icon_color
    rrect(ax, x, y, w, h, bg_color, border_color, alpha=0.9, lw=1.3, rad=0.25, zorder=zorder)
    # Icon
    service_icon(ax, x + 2.2, y + h/2, icon_abbrev, icon_color, size=1.5, zorder=zorder+2)
    # Labels
    ax.text(x + 4.8, y + h/2 + 0.6, label, fontsize=fontsize, fontweight='bold',
            ha='left', va='center', color=C['text_dark'], zorder=zorder+1)
    if sublabel:
        ax.text(x + 4.8, y + h/2 - 0.9, sublabel, fontsize=fontsize-2,
                ha='left', va='center', color=C['text_light'], zorder=zorder+1)


def fn_box(ax, x, y, w, h, label, color, border_color, fontsize=5.8, zorder=6):
    """Small function/handler box."""
    rrect(ax, x, y, w, h, color, border_color, alpha=0.85, lw=0.9, rad=0.15, zorder=zorder)
    ax.text(x + w/2, y + h/2, label, fontsize=fontsize, ha='center', va='center',
            color=C['text_dark'], zorder=zorder+1)


def section_title(ax, x, y, text, color, fontsize=9, bg='white'):
    ax.text(x, y, text, fontsize=fontsize, fontweight='bold', color=color,
            ha='left', va='center', zorder=12,
            bbox=dict(boxstyle='round,pad=0.3', facecolor=bg, edgecolor=color,
                     linewidth=1.5, alpha=0.95))


def arr(ax, x1, y1, x2, y2, color=None, lw=1.4, style='->', ls='-', zorder=4):
    if color is None:
        color = C['arrow']
    ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle=style, color=color, lw=lw,
                               linestyle=ls, shrinkA=1, shrinkB=1),
                zorder=zorder)


def draw_diagram():
    fig, ax = create_figure()

    # ── Title ──────────────────────────────────────────────────────────
    ax.text(80, 118, 'BeFaaS  --  Webservice Experiment Infrastructure',
            fontsize=18, fontweight='bold', ha='center', va='center',
            color=C['text_dark'], zorder=10)
    ax.text(80, 116, 'Benchmarking Framework for FaaS, Microservices & Monolith Architectures on AWS',
            fontsize=10, ha='center', va='center', color=C['text_light'], zorder=10)

    # ══════════════════════════════════════════════════════════════════
    # TOP ROW: External Entry Points (y: 108-114)
    # ══════════════════════════════════════════════════════════════════

    svc_box(ax, 2, 108, 19, 5.5, 'Artillery', 'Load Generator (3 req/s)',
            '>>>', C['artillery'], C['artillery_bg'], C['artillery'])

    svc_box(ax, 26, 108, 19, 5.5, 'CloudFront', 'Edge Authentication',
            'CF', C['cloudfront'], C['alb_bg'], C['cloudfront'])

    svc_box(ax, 56, 108, 19, 5.5, 'API Gateway v2', 'HTTP API (FaaS)',
            'API', C['apigw'], C['apigw_bg'], C['apigw'])

    svc_box(ax, 86, 108, 22, 5.5, 'App Load Balancer', 'ECS (Micro / Mono)',
            'ALB', C['alb'], C['alb_bg'], C['alb'])

    # Arrows between top components
    arr(ax, 21, 111, 26, 111, C['artillery'], 1.8)
    arr(ax, 21, 109.5, 56, 109.5, C['artillery'], 1.2, ls='--')
    arr(ax, 21, 108.8, 86, 108.8, C['artillery'], 1.2, ls='--')
    arr(ax, 45, 110.5, 56, 110.5, C['cloudfront'], 1.4)

    ax.text(38, 112.3, 'Edge Auth path', fontsize=6.5, color=C['text_muted'],
            ha='center', style='italic', zorder=10)
    ax.text(52, 108, 'Direct path (no edge auth)', fontsize=5.5, color=C['text_muted'],
            ha='center', style='italic', zorder=10)

    # ══════════════════════════════════════════════════════════════════
    # VPC Boundary (y: 2-106)
    # ══════════════════════════════════════════════════════════════════
    rrect(ax, 1, 2, 109, 104, C['vpc_bg'], C['vpc_border'],
          alpha=0.12, lw=2.5, rad=0.6, zorder=0)
    section_title(ax, 2.5, 105.5, '  VPC  10.0.0.0/16  --  Availability Zone A + B  ',
                  C['vpc_border'], fontsize=9)

    # ── Public Subnet (y: 98-104) ──────────────────────────────────
    rrect(ax, 2.5, 97, 106, 7.5, C['pub_subnet'], C['pub_border'],
          alpha=0.2, lw=1.5, rad=0.3, zorder=1)
    section_title(ax, 3.5, 104, ' Public Subnet ', C['pub_border'], fontsize=8)

    svc_box(ax, 15, 98.5, 18, 4.5, 'Internet Gateway', 'VPC Entry Point',
            'IGW', C['igw'], 'white', C['igw'])

    svc_box(ax, 50, 98.5, 18, 4.5, 'NAT Gateway', 'Outbound Internet',
            'NAT', C['nat'], 'white', C['nat'])

    # Arrows from top to public subnet
    arr(ax, 65, 108, 33, 103, C['igw'], 1.5)
    arr(ax, 97, 108, 68, 103, C['igw'], 1.5)

    # ══════════════════════════════════════════════════════════════════
    # ① FaaS / Serverless (y: 66-96)
    # ══════════════════════════════════════════════════════════════════
    rrect(ax, 2.5, 64, 106, 32, C['faas_bg'], C['faas'],
          alpha=0.2, lw=2, rad=0.4, zorder=1)
    section_title(ax, 3.5, 95.5,
                  '  1   FaaS (Serverless)  --  AWS Lambda  ',
                  C['faas'], fontsize=9, bg=C['faas_bg'])

    # API Gateway inside
    svc_box(ax, 5, 88, 18, 4.5, 'API Gateway v2', 'HTTP API Routes',
            'API', C['apigw'], 'white', C['apigw'])

    arr(ax, 24, 98.5, 14, 92.5, C['apigw'], 1.5)

    # Lambda functions grid
    lambda_fns = [
        'frontend', 'login', 'register', 'getproduct', 'listproducts',
        'searchproducts', 'getcart', 'addcartitem', 'emptycart',
        'cartkvstorage', 'checkout', 'payment', 'shipmentquote',
        'shiporder', 'currency', 'supportedcurrencies', 'email',
        'getads', 'listrecommendations'
    ]

    cols, fn_w, fn_h = 7, 13.5, 3.0
    gap_x, gap_y = 0.8, 0.6
    sx, sy = 5, 65.5

    for i, fn in enumerate(lambda_fns):
        col = i % cols
        row = i // cols
        fx = sx + col * (fn_w + gap_x)
        fy = sy + (2 - row) * (fn_h + gap_y)
        fn_box(ax, fx, fy, fn_w, fn_h, f'{fn}', C['lambda_bg'], C['lambda'],
               fontsize=6, zorder=6)
        # Lambda icon
        ax.text(fx + 0.8, fy + fn_h/2, 'λ', fontsize=8, fontweight='bold',
                ha='center', va='center', color=C['lambda'], zorder=7, alpha=0.6)

    # Arrow from API GW to functions
    arr(ax, 14, 88, 14, 76, C['lambda'], 1.5)
    arr(ax, 23, 88, 40, 76, C['lambda'], 1.2, ls='--')

    # Lambda-to-Lambda annotation
    ax.text(80, 88, 'Lambda-to-Lambda\ndirect invoke (AWS SDK)\nBypasses API Gateway',
            fontsize=7, color=C['faas'], ha='center', va='center', zorder=10,
            bbox=dict(boxstyle='round,pad=0.3', facecolor='white',
                     edgecolor=C['faas'], linewidth=1, alpha=0.9))
    # Bidirectional arrow between functions
    arr(ax, 67, 74, 75, 86, C['faas'], 1.0, ls='--')

    # ══════════════════════════════════════════════════════════════════
    # ② Microservices (y: 30-63)
    # ══════════════════════════════════════════════════════════════════
    rrect(ax, 2.5, 29, 106, 34, C['micro_bg'], C['micro'],
          alpha=0.15, lw=2, rad=0.4, zorder=1)
    section_title(ax, 3.5, 62.5,
                  '  2   Microservices  --  ECS Fargate + Cloud Map  ',
                  C['micro'], fontsize=9, bg=C['micro_bg'])

    # ALB
    svc_box(ax, 5, 55, 18, 4.5, 'App Load Balancer', 'Target Groups',
            'ALB', C['alb'], 'white', C['alb'])

    arr(ax, 59, 98.5, 14, 59.5, C['alb'], 1.2, ls='--')

    # ECS Services
    services = [
        ('Frontend Service', ':3000', 5),
        ('Product Service', ':3001', 25),
        ('Cart Service', ':3002', 45),
        ('Order Service', ':3003', 65),
        ('Content Service', ':3004', 85),
    ]

    for name, port, sx_pos in services:
        rrect(ax, sx_pos, 42, 18, 8.5, 'white', C['micro'],
              alpha=0.9, lw=1.3, rad=0.25, zorder=6)
        # ECS icon
        service_icon(ax, sx_pos + 2.2, 48.5, 'ECS', C['ecs'], size=1.4, zorder=8)
        ax.text(sx_pos + 9, 48.5, name, fontsize=7, fontweight='bold',
                ha='center', va='center', color=C['text_dark'], zorder=7)
        ax.text(sx_pos + 9, 46.5, f'Fargate  {port}', fontsize=6,
                ha='center', va='center', color=C['text_light'], zorder=7)
        # Function list inside
        ax.text(sx_pos + 9, 44.2, 'Auto-scaling', fontsize=5.5,
                ha='center', va='center', color=C['micro'], style='italic', zorder=7)

    # Arrow from ALB to Frontend Service
    arr(ax, 23, 57, 14, 50.5, C['alb'], 1.5)

    # Service-to-service arrows
    for i in range(len(services) - 1):
        x1 = services[i][2] + 18
        x2 = services[i+1][2]
        arr(ax, x1, 46, x2, 46, C['micro'], 0.8, style='<->', ls=':')

    # Cloud Map
    svc_box(ax, 5, 30.5, 20, 4.5, 'AWS Cloud Map', '{project}.local DNS',
            'CM', C['cloudmap'], 'white', C['cloudmap'])

    # Auto-Scaling
    svc_box(ax, 76, 30.5, 27, 4.5, 'Auto-Scaling', 'CPU / RequestCount / Latency',
            'AS', C['ecs'], 'white', C['ecs'])

    # Dashed line from Cloud Map to services
    ax.plot([25, 76], [32.7, 32.7], color=C['cloudmap'], linewidth=1,
            linestyle=':', zorder=3, alpha=0.6)
    for s in services:
        arr(ax, s[2] + 9, 42, s[2] + 9, 35, C['cloudmap'], 0.6, ls='--')

    # ══════════════════════════════════════════════════════════════════
    # ③ Monolith (y: 3-28)
    # ══════════════════════════════════════════════════════════════════
    rrect(ax, 2.5, 3, 106, 25, C['mono_bg'], C['mono'],
          alpha=0.15, lw=2, rad=0.4, zorder=1)
    section_title(ax, 3.5, 27.5,
                  '  3   Monolith  --  Single ECS Fargate Container  ',
                  C['mono'], fontsize=9, bg=C['mono_bg'])

    # ALB
    svc_box(ax, 5, 19.5, 18, 4.5, 'App Load Balancer', 'Single Target',
            'ALB', C['alb'], 'white', C['alb'])

    arr(ax, 59, 98.5, 14, 24, C['alb'], 1.0, ls=':')

    # Monolith container outline
    rrect(ax, 27, 4, 79, 20, '#E8F5E9', C['mono'],
          alpha=0.3, lw=1.8, rad=0.3, zorder=2)
    ax.text(66.5, 23, 'ECS Fargate  --  Single Container  (Koa.js)',
            fontsize=8.5, fontweight='bold', ha='center', va='center',
            color=C['mono'], zorder=10)

    # Functions inside monolith
    mono_fns = [
        'frontend', 'login', 'register', 'getproduct', 'listproducts',
        'searchproducts', 'getcart', 'addcartitem', 'emptycart',
        'cartkvstorage', 'checkout', 'payment', 'shipmentquote',
        'shiporder', 'currency', 'email', 'getads', 'listrecommendations'
    ]
    m_cols, m_w, m_h = 6, 12.2, 2.8
    m_gx, m_gy = 0.6, 0.4
    m_sx, m_sy = 28.5, 5

    for i, fn in enumerate(mono_fns):
        col = i % m_cols
        row = i // m_cols
        mx = m_sx + col * (m_w + m_gx)
        my = m_sy + (2 - row) * (m_h + m_gy)
        fn_box(ax, mx, my, m_w, m_h, fn, '#FFFFFF', C['mono'],
               fontsize=5.5, zorder=5)

    # In-process label
    ax.text(93, 7, 'All calls\nin-process\n(0ms overhead)',
            fontsize=7, color=C['mono'], ha='center', va='center',
            fontweight='bold', zorder=10,
            bbox=dict(boxstyle='round,pad=0.3', facecolor='white',
                     edgecolor=C['mono'], linewidth=1, alpha=0.9))

    arr(ax, 23, 21.5, 27, 16, C['alb'], 1.5)

    # ══════════════════════════════════════════════════════════════════
    # RIGHT PANEL: Shared Services (x: 112-158)
    # ══════════════════════════════════════════════════════════════════

    # ── Shared Services ──────────────────────────────────────────────
    rrect(ax, 112, 72, 46, 44, C['shared_bg'], C['shared'],
          alpha=0.12, lw=2, rad=0.4, zorder=1)
    section_title(ax, 113, 115.5, ' Shared Services ', C['shared'], fontsize=9.5)

    svc_box(ax, 114, 104, 42, 6, 'Redis', 'EC2 t3a.medium  |  Docker  |  Cart & Session Storage',
            'R', C['redis'], C['redis_bg'], C['redis'], fontsize=8.5)

    svc_box(ax, 114, 95.5, 42, 6, 'AWS Cognito', 'User Pool  |  JWT  |  USER_PASSWORD_AUTH',
            'ID', C['cognito'], C['cognito_bg'], C['cognito'], fontsize=8.5)

    svc_box(ax, 114, 87, 42, 6, 'Amazon S3', 'Function Artifacts & Deployment Packages',
            'S3', C['s3'], C['s3_bg'], C['s3'], fontsize=8.5)

    svc_box(ax, 114, 78.5, 42, 6, 'CloudWatch', 'Logs  |  Metrics  |  Container Insights',
            'CW', C['cw'], C['cw_bg'], C['cw'], fontsize=8.5)

    ax.text(135, 73.5, 'Used by all three architecture options',
            fontsize=7, color=C['shared'], ha='center', style='italic', zorder=10)

    # Connection arrows from VPC to shared services
    arr(ax, 108.5, 80, 114, 82, C['redis'], 1.2, ls='--')
    arr(ax, 108.5, 90, 114, 90, C['cw'], 1.0, ls='--')

    # ── Authentication Options ───────────────────────────────────────
    rrect(ax, 112, 38, 46, 32, C['auth_bg'], C['auth'],
          alpha=0.12, lw=2, rad=0.4, zorder=1)
    section_title(ax, 113, 69.5, ' Authentication Options ', C['auth'], fontsize=9)

    auth_options = [
        ('A', 'None (Redis-based)', 'Simple session validation\nNo cryptographic verification'),
        ('B', 'Service-Integrated', 'Cognito JWT tokens\nAWS-managed validation'),
        ('C', 'Edge Auth', 'CloudFront + Lambda@Edge\nEd25519 signing  |  45s TTL'),
        ('D', 'Manual Crypto', 'Argon2id-EdDSA  or  Bcrypt-HS256\nSelf-managed JWT signing'),
    ]

    ay = 63
    for letter, name, desc in auth_options:
        # Badge
        circle = Circle((115.5, ay), 1.3, facecolor=C['auth'], edgecolor='white',
                        linewidth=1.2, zorder=10)
        ax.add_patch(circle)
        ax.text(115.5, ay, letter, fontsize=8, fontweight='bold', ha='center',
                va='center', color='white', zorder=11)
        ax.text(119, ay + 0.7, name, fontsize=7.5, fontweight='bold',
                ha='left', va='center', color=C['text_dark'], zorder=10)
        ax.text(119, ay - 1.2, desc, fontsize=6, ha='left', va='center',
                color=C['text_light'], zorder=10, linespacing=1.5)
        ay -= 7.5

    # ── Observability & Tracing ──────────────────────────────────────
    rrect(ax, 112, 2, 46, 34.5, C['obs_bg'], C['obs'],
          alpha=0.12, lw=2, rad=0.4, zorder=1)
    section_title(ax, 113, 36, ' Observability & Tracing ', C['obs'], fontsize=9)

    obs_items = [
        ('Handler Metrics', 'HTTP method : path : status timing per request'),
        ('RPC Metrics', 'contextId : xPair : callee : callId inter-function timing'),
        ('Cold Start Detection', 'Per-function first invocation tracking'),
        ('Request Tracing', 'X-Context + X-Pair header propagation'),
        ('CloudWatch Logs', '/aws/lambda/{run_id}/{fn}  |  /aws/ecs/{project}/{svc}'),
        ('CloudWatch Metrics', 'Invocations, Duration, Errors, Throttles, ConcurrentExec'),
    ]

    oy = 31.5
    for title, desc in obs_items:
        ax.text(115, oy + 0.3, title, fontsize=7, fontweight='bold',
                ha='left', va='center', color=C['text_dark'], zorder=10)
        ax.text(115, oy - 1.5, desc, fontsize=5.8,
                ha='left', va='center', color=C['text_light'], zorder=10)
        oy -= 4.8

    # ══════════════════════════════════════════════════════════════════
    # LEGEND at bottom
    # ══════════════════════════════════════════════════════════════════

    # Separator
    ax.plot([2, 158], [1.2, 1.2], color='#E0E0E0', linewidth=1, zorder=2)

    legend_items = [
        (C['faas'], '1  FaaS'),
        (C['micro'], '2  Microservices'),
        (C['mono'], '3  Monolith'),
        (C['shared'], 'Shared Services'),
        (C['auth'], 'Authentication'),
        (C['obs'], 'Observability'),
    ]

    lx = 5
    for color, label in legend_items:
        rrect(ax, lx, -0.3, 2, 1.2, color, color, alpha=0.85, lw=0, rad=0.1, zorder=10)
        ax.text(lx + 3, 0.3, label, fontsize=7, ha='left', va='center',
                color=C['text_dark'], zorder=10)
        lx += 22

    ax.text(140, 0.3, 'Each experiment deploys exactly ONE architecture option',
            fontsize=6.5, color=C['text_muted'], ha='center', va='center',
            style='italic', zorder=10)

    return fig


if __name__ == '__main__':
    fig = draw_diagram()
    output = '/Users/jakob/WebstormProjects/BeFaaS-framework2/doc/infrastructure-diagram.png'
    fig.savefig(output, dpi=200, bbox_inches='tight',
                facecolor='white', edgecolor='none', pad_inches=0.3)
    plt.close(fig)
    print(f'Diagram saved to {output}')
