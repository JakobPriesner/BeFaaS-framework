#!/usr/bin/env python3
"""
Analyze AWS CloudWatch errors from logs to identify root causes
"""

import json
import sys
import re
from collections import defaultdict, Counter

def parse_aws_logs(log_file):
    """Parse AWS CloudWatch logs and extract errors"""
    errors = []

    with open(log_file, 'r') as f:
        for line in f:
            try:
                entry = json.loads(line.strip())
                message = entry.get('message', '')

                # Check if it's an error
                if 'ERROR' in message or 'Error' in message:
                    errors.append({
                        'timestamp': entry.get('timestamp'),
                        'message': message,
                        'raw': entry
                    })
            except json.JSONDecodeError:
                continue

    return errors

def categorize_errors(errors):
    """Categorize errors by type and extract key information"""
    categories = defaultdict(list)
    error_types = Counter()

    for error in errors:
        message = error['message']

        # Extract error type
        error_type = 'Unknown'
        error_details = ''

        # Parse JSON error message if present
        try:
            # Look for JSON object in message
            json_match = re.search(r'\{.*"errorType".*\}', message, re.DOTALL)
            if json_match:
                error_data = json.loads(json_match.group(0))
                error_type = error_data.get('errorType', 'Unknown')
                error_details = error_data.get('errorMessage', '')
                stack = error_data.get('stack', [])

                categories[error_type].append({
                    'type': error_type,
                    'message': error_details,
                    'stack': stack,
                    'timestamp': error['timestamp']
                })

                error_types[error_type] += 1
                continue
        except:
            pass

        # Fallback: extract from text
        if 'ImportModuleError' in message:
            error_type = 'Runtime.ImportModuleError'
            module_match = re.search(r"Cannot find module '([^']+)'", message)
            if module_match:
                error_details = f"Missing module: {module_match.group(1)}"
        elif 'UserCodeSyntaxError' in message:
            error_type = 'Runtime.UserCodeSyntaxError'
            syntax_match = re.search(r'SyntaxError: (.+?)(?:\\n|$)', message)
            if syntax_match:
                error_details = syntax_match.group(1)
        elif 'TimeoutError' in message or 'Task timed out' in message:
            error_type = 'Task.TimeoutError'
            error_details = 'Function execution timeout'
        elif 'MemoryError' in message or 'out of memory' in message.lower():
            error_type = 'Runtime.MemoryError'
            error_details = 'Out of memory'

        categories[error_type].append({
            'type': error_type,
            'message': error_details or message[:200],
            'timestamp': error['timestamp']
        })

        error_types[error_type] += 1

    return categories, error_types

def analyze_import_errors(categories):
    """Analyze import module errors to find missing dependencies"""
    if 'Runtime.ImportModuleError' not in categories:
        return {}

    missing_modules = Counter()

    for error in categories['Runtime.ImportModuleError']:
        message = error['message']
        module_match = re.search(r"Missing module: (.+)", message)
        if module_match:
            module = module_match.group(1)
            missing_modules[module] += 1
        else:
            # Try to extract from full message
            module_match = re.search(r"Cannot find module '([^']+)'", message)
            if module_match:
                missing_modules[module_match.group(1)] += 1

    return missing_modules

def generate_recommendations(categories, error_types):
    """Generate actionable recommendations based on error patterns"""
    recommendations = []

    # ImportModuleError
    if 'Runtime.ImportModuleError' in error_types:
        count = error_types['Runtime.ImportModuleError']
        missing = analyze_import_errors(categories)

        recommendations.append({
            'severity': 'CRITICAL',
            'issue': f'Import Module Errors ({count} occurrences)',
            'description': 'Lambda functions cannot find required modules',
            'missing_modules': dict(missing),
            'solution': [
                '1. Identify missing modules from the list below',
                '2. Update FaaS build.js to copy required shared modules',
                '3. Add missing modules to deployment packages',
                '4. Verify module paths are correct relative to handler'
            ]
        })

    # UserCodeSyntaxError
    if 'Runtime.UserCodeSyntaxError' in error_types:
        count = error_types['Runtime.UserCodeSyntaxError']
        recommendations.append({
            'severity': 'CRITICAL',
            'issue': f'Syntax Errors in Code ({count} occurrences)',
            'description': 'Lambda functions have JavaScript syntax errors',
            'solution': [
                '1. Review the error messages for specific syntax issues',
                '2. Check for empty or malformed JSON files (package.json)',
                '3. Validate all JavaScript files compile without errors',
                '4. Run local tests before deployment'
            ]
        })

    # Timeout errors
    if 'Task.TimeoutError' in error_types:
        count = error_types['Task.TimeoutError']
        recommendations.append({
            'severity': 'WARNING',
            'issue': f'Function Timeout Errors ({count} occurrences)',
            'description': 'Lambda functions are timing out during execution',
            'solution': [
                '1. Increase Lambda function timeout in Terraform configuration',
                '2. Optimize function code to execute faster',
                '3. Check for infinite loops or blocking operations',
                '4. Review external API call timeouts'
            ]
        })

    # Memory errors
    if 'Runtime.MemoryError' in error_types:
        count = error_types['Runtime.MemoryError']
        recommendations.append({
            'severity': 'WARNING',
            'issue': f'Out of Memory Errors ({count} occurrences)',
            'description': 'Lambda functions are running out of memory',
            'solution': [
                '1. Increase Lambda function memory in Terraform configuration',
                '2. Optimize memory usage in function code',
                '3. Check for memory leaks',
                '4. Process data in smaller chunks'
            ]
        })

    return recommendations

def print_report(categories, error_types, recommendations, output_file=None):
    """Generate and print error analysis report"""
    report = []

    report.append("=" * 80)
    report.append("AWS CLOUDWATCH ERROR ANALYSIS")
    report.append("=" * 80)
    report.append("")

    # Error summary
    report.append("ERROR SUMMARY")
    report.append("-" * 80)
    report.append(f"Total error occurrences: {sum(error_types.values())}")
    report.append(f"Unique error types: {len(error_types)}")
    report.append("")

    # Error breakdown
    report.append("ERROR BREAKDOWN BY TYPE")
    report.append("-" * 80)
    for error_type, count in error_types.most_common():
        percentage = (count / sum(error_types.values()) * 100) if sum(error_types.values()) > 0 else 0
        report.append(f"  {error_type:50s}: {count:6d} ({percentage:5.1f}%)")
    report.append("")

    # Detailed error examples
    report.append("DETAILED ERROR EXAMPLES")
    report.append("-" * 80)
    for error_type, errors in sorted(categories.items()):
        if not errors:
            continue

        report.append(f"\n{error_type}")
        report.append("  " + "-" * 76)

        # Show first 3 unique error messages
        unique_messages = {}
        for error in errors:
            msg = error['message'][:150]
            if msg not in unique_messages:
                unique_messages[msg] = 1
            else:
                unique_messages[msg] += 1

            if len(unique_messages) > 3:
                break

        for msg, count in list(unique_messages.items())[:3]:
            report.append(f"  Message: {msg}")
            if count > 1:
                report.append(f"  (Occurred {count} times)")
            report.append("")

    # Recommendations
    if recommendations:
        report.append("")
        report.append("=" * 80)
        report.append("RECOMMENDATIONS & SOLUTIONS")
        report.append("=" * 80)
        report.append("")

        for i, rec in enumerate(recommendations, 1):
            report.append(f"{i}. [{rec['severity']}] {rec['issue']}")
            report.append(f"   {rec['description']}")
            report.append("")

            if 'missing_modules' in rec and rec['missing_modules']:
                report.append("   Missing Modules:")
                for module, count in sorted(rec['missing_modules'].items(), key=lambda x: x[1], reverse=True):
                    report.append(f"     - {module} (failed {count} times)")
                report.append("")

            report.append("   Solution:")
            for step in rec['solution']:
                report.append(f"     {step}")
            report.append("")

    report.append("=" * 80)

    report_text = "\n".join(report)

    # Print to console
    print(report_text)

    # Save to file if specified
    if output_file:
        with open(output_file, 'w') as f:
            f.write(report_text)
        print(f"\n✓ Error analysis report saved to {output_file}")

    return report_text

def main(aws_log_file, output_dir):
    """Main analysis function"""
    print(f"Analyzing AWS CloudWatch logs: {aws_log_file}")
    print("This may take a moment for large log files...\n")

    # Parse logs
    errors = parse_aws_logs(aws_log_file)

    if not errors:
        print("✓ No errors found in AWS CloudWatch logs!")
        return 0

    print(f"Found {len(errors)} error entries\n")

    # Categorize errors
    categories, error_types = categorize_errors(errors)

    # Generate recommendations
    recommendations = generate_recommendations(categories, error_types)

    # Generate report
    output_file = f"{output_dir}/error_analysis.txt"
    print_report(categories, error_types, recommendations, output_file)

    # Return exit code based on severity
    if any(rec['severity'] == 'CRITICAL' for rec in recommendations):
        return 2
    elif recommendations:
        return 1
    return 0

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <aws_log_file> <output_directory>")
        sys.exit(1)

    exit_code = main(sys.argv[1], sys.argv[2])
    sys.exit(exit_code)