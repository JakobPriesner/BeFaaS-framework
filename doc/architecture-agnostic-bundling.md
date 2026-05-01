# Architektur-agnostische Paketierung im BeFaaS-Framework

## 1. Einleitung und Motivation

Das BeFaaS-Framework implementiert ein architektur-agnostisches Build-System, das dieselbe Geschäftslogik (Funktionen) in drei verschiedene Deployment-Architekturen transformiert: **FaaS** (Function-as-a-Service), **Microservices** und **Monolith**. Diese Trennung ermöglicht faire Vergleiche der Architekturen unter identischer Funktionalität.

### 1.1 Kernprinzip

Die Geschäftslogik ist in **architektur-neutralen Funktionen** implementiert, die eine einheitliche Signatur verwenden:

```javascript
async function handle(event, ctx) {
  // event: Eingabedaten (JSON-Payload)
  // ctx: Kontext mit call(), db, contextId, etc.
  return result;
}
```

Jede Funktion kann über `ctx.call(functionName, payload)` andere Funktionen aufrufen. Die Build-Prozesse transformieren diese Aufrufe entsprechend der Zielarchitektur:
- **FaaS**: Direkte Lambda-Invokation oder HTTP via API Gateway
- **Microservices**: HTTP-Aufrufe zwischen Services oder In-Process-Aufrufe
- **Monolith**: Direkte In-Process-Aufrufe (kein Netzwerk)

---

## 2. Quelldatei-Struktur

### 2.1 Funktionsverzeichnis

Alle Geschäftsfunktionen befinden sich in `experiments/webservice/functions/`:

```
functions/
├── addcartitem/
│   └── index.js          # Artikel zum Warenkorb hinzufügen
├── cartkvstorage/
│   └── index.js          # Key-Value-Speicher für Warenkorb
├── checkout/
│   └── index.js          # Checkout-Prozess
├── currency/
│   └── index.js          # Währungsumrechnung
├── email/
│   └── index.js          # E-Mail-Versand
├── emptycart/
│   └── index.js          # Warenkorb leeren
├── frontend/
│   ├── index.js          # FaaS-Einstiegspunkt
│   ├── handlers.js       # Gemeinsame Handler-Logik
│   └── html_templates/   # HTML-Templates
│       ├── home.html
│       ├── product.html
│       ├── cart.html
│       └── order.html
├── getads/
│   └── index.js          # Werbeanzeigen abrufen
├── getcart/
│   └── index.js          # Warenkorb abrufen
├── getproduct/
│   └── index.js          # Produkt abrufen
├── listproducts/
│   └── index.js          # Produktliste abrufen
├── listrecommendations/
│   └── index.js          # Empfehlungen abrufen
├── login/
│   └── index.js          # Benutzer-Anmeldung
├── payment/
│   └── index.js          # Zahlungsverarbeitung
├── register/
│   └── index.js          # Benutzer-Registrierung
├── searchproducts/
│   └── index.js          # Produktsuche
├── shipmentquote/
│   └── index.js          # Versandkosten berechnen
├── shiporder/
│   └── index.js          # Versand auslösen
└── supportedcurrencies/
    └── index.js          # Unterstützte Währungen
```

### 2.2 Gemeinsame Datenmodule

```
experiments/webservice/
├── currency/
│   └── exchangerates.js  # Wechselkurse (EUR-basiert)
└── productcatalog/
    └── products.js       # Produktkatalog
```

### 2.3 Authentifizierungs-Strategien

```
experiments/webservice/authentication/
├── none/
│   ├── index.js          # verifyJWT() -> true (No-Op)
│   ├── login.js          # Mock-Login ohne Cognito
│   └── register.js       # Mock-Registrierung ohne Cognito
├── service-integrated/
│   └── index.js          # JWT-Verifizierung via AWS Cognito
└── service-integrated-manual/
    └── index.js          # Alternative JWT-Implementierung
```

### 2.4 Architektur-spezifische Dateien

```
experiments/webservice/architectures/
├── shared/               # Gemeinsame Module für alle Architekturen
│   ├── authConfig.js     # Welche Funktionen Auth benötigen
│   ├── call.js           # BaseCallProvider-Basisklasse
│   └── serviceConfig.js  # Funktion-zu-Service-Mapping
├── faas/
│   ├── build.js          # Build-Skript
│   ├── index.js          # Lambda-Handler-Wrapper
│   ├── restHandler.js    # REST-Handler mit Auth
│   ├── call.js           # FaaSCallProvider
│   └── package.json      # NPM-Abhängigkeiten
├── microservices/
│   ├── build.js          # Build-Skript
│   ├── shared/
│   │   ├── call.js       # MicroservicesCallProvider
│   │   └── libConfig.js  # Konfiguration
│   ├── cart-service/
│   │   └── index.js      # Express-Server
│   ├── content-service/
│   │   └── index.js
│   ├── frontend-service/
│   │   └── index.js
│   ├── order-service/
│   │   └── index.js
│   └── product-service/
│       └── index.js
└── monolith/
    ├── build.js          # Build-Skript
    ├── index.js          # Koa-Server
    ├── call.js           # MonolithCallProvider
    ├── package.json
    └── Dockerfile
```

---

## 3. experiment.json - Konfigurationsdatei

Die `experiment.json` definiert, welche Funktionen bereitgestellt werden und welchen Cloud-Provider sie nutzen:

```json
{
  "services": {
    "redisAws": {},
    "workload": {
      "config": "./workload-constant.yml"
    }
  },
  "program": {
    "functions": {
      "frontend": {
        "provider": "aws",
        "calls": ["getcart", "getproduct", "currency", ...]
      },
      "checkout": {
        "provider": "aws",
        "calls": ["getcart", "getproduct", "currency", ...]
      },
      "email": { "provider": "aws" },
      "currency": { "provider": "aws" },
      ...
    }
  }
}
```

**Bedeutung der Felder:**
- `provider`: Cloud-Provider (aws, google, azure, tinyfaas, openfaas)
- `calls`: Liste der Funktionen, die diese Funktion aufruft (für Call-Graph-Analyse)

---

## 4. FaaS Build-Prozess (faas/build.js)

### 4.1 Überblick

Der FaaS-Build erstellt für jede Funktion ein eigenständiges Deployment-Paket. Jedes Paket ist autark und kann unabhängig als AWS Lambda-Funktion deployed werden.

### 4.2 Build-Modi

**Minimal-Modus (Standard):** Baut nur Funktionen aus `experiment.json`
```javascript
const experimentConfig = JSON.parse(fs.readFileSync(experimentJsonPath, 'utf8'));
useCases = Object.keys(experimentConfig.program.functions);
```

**All-Modus:** Baut alle Funktionen im functions-Verzeichnis
```javascript
useCases = fs.readdirSync(functionsDir).filter(file => {
  return fs.statSync(path.join(functionsDir, file)).isDirectory();
});
```

### 4.3 Schritte für jede Funktion

Der Build-Prozess `buildSingleFunction(useCase, tmpDir, authStrategy)` führt folgende Schritte aus:

#### Schritt 1: Verzeichnis erstellen
```javascript
if (!fs.existsSync(tmpDir)) {
  fs.mkdirSync(tmpDir, { recursive: true });
}
```

#### Schritt 2: Lambda-Handler kopieren
```javascript
// index.js - Lambda-Einstiegspunkt
const indexPath = path.join(__dirname, 'index.js');
fs.copyFileSync(indexPath, path.join(tmpDir, 'index.js'));

// restHandler.js - REST-Handler mit Auth-Logik
const restHandlerPath = path.join(__dirname, 'restHandler.js');
fs.copyFileSync(restHandlerPath, path.join(tmpDir, 'restHandler.js'));

// call.js - FaaS-Call-Provider
const callPath = path.join(__dirname, 'call.js');
fs.copyFileSync(callPath, path.join(tmpDir, 'call.js'));
```

#### Schritt 3: Shared-Module kopieren
```javascript
const sharedFiles = ['authConfig.js', 'call.js', 'serviceConfig.js'];
for (const file of sharedFiles) {
  fs.copyFileSync(
    path.join(__dirname, '..', 'shared', file),
    path.join(tmpDir, 'shared', file)
  );
}
```

#### Schritt 4: Package.json kopieren
```javascript
fs.copyFileSync(
  path.join(__dirname, 'package.json'),
  path.join(tmpDir, 'package.json')
);
```

#### Schritt 5: Funktions-Handler transformieren
```javascript
// Quellpfad bestimmen (Standard oder Auth-Override)
let useCasePath;
if (authOverrideFunctions.includes(useCase)) {
  const customHandlerPath = path.join(authStrategyDir, `${useCase}.js`);
  if (fs.existsSync(customHandlerPath)) {
    useCasePath = customHandlerPath;  // z.B. 'none' auth hat eigene login.js
  }
}

// Handler-Code laden und Pfade transformieren
let handlerCode = fs.readFileSync(useCasePath, 'utf8');

// Require-Pfade anpassen: ../../currency -> ./currency
handlerCode = handlerCode.replace(
  /require\(['"]\.\.\/\.\.\/([^'"]+)['"]\)/g,
  "require('./$1')"
);

// @befaas/lib-Initialisierung sicherstellen
if (!handlerCode.includes("@befaas/lib")) {
  handlerCode = "require('@befaas/lib');\n" + handlerCode;
}

fs.writeFileSync(path.join(tmpDir, 'handler.js'), handlerCode);
```

#### Schritt 6: Auth-Strategie kopieren
```javascript
const authFiles = fs.readdirSync(authStrategyDir);
authFiles.forEach(file => {
  fs.copyFileSync(
    path.join(authStrategyDir, file),
    path.join(tmpDir, 'auth', file)
  );
});
```

#### Schritt 7: Funktions-spezifische Abhängigkeiten kopieren
```javascript
const sharedModuleDeps = {
  'currency': ['currency/exchangerates.js'],
  'supportedcurrencies': ['currency/exchangerates.js'],
  'getproduct': ['productcatalog/products.js'],
  'listproducts': ['productcatalog/products.js'],
  'searchproducts': ['productcatalog/products.js']
};

if (sharedModuleDeps[useCase]) {
  for (const modulePath of sharedModuleDeps[useCase]) {
    // Kopiere z.B. currency/exchangerates.js nach tmpDir/currency/
    fs.copyFileSync(srcModulePath, destModulePath);
  }
}
```

#### Schritt 8: experiment.json kopieren
```javascript
fs.copyFileSync(experimentJsonPath, path.join(tmpDir, 'experiment.json'));
```

### 4.4 Frontend-Funktion (Sonderfall)

Die Frontend-Funktion verwendet einen Router-Pattern und wird komplett kopiert:

```javascript
if (useCase === 'frontend') {
  copyDirectoryRecursive(useCaseDir, tmpDir);
  fs.copyFileSync(packagePath, path.join(tmpDir, 'package.json'));
  fs.copyFileSync(experimentJsonPath, path.join(tmpDir, 'experiment.json'));
  return;
}
```

### 4.5 Output-Struktur (FaaS)

```
_build/
├── addcartitem/
│   ├── index.js          # Lambda-Einstiegspunkt
│   ├── restHandler.js    # REST-Handler mit Auth
│   ├── call.js           # FaaS-Call-Provider
│   ├── handler.js        # Transformierte Geschäftslogik
│   ├── package.json
│   ├── experiment.json
│   ├── auth/
│   │   └── index.js      # Auth-Strategie
│   └── shared/
│       ├── authConfig.js
│       ├── call.js
│       └── serviceConfig.js
├── currency/
│   ├── index.js
│   ├── restHandler.js
│   ├── call.js
│   ├── handler.js
│   ├── package.json
│   ├── experiment.json
│   ├── auth/
│   ├── shared/
│   └── currency/
│       └── exchangerates.js   # Funktions-spezifische Abhängigkeit
├── frontend/
│   ├── index.js          # Frontend-eigener Einstiegspunkt
│   ├── handlers.js
│   ├── html_templates/
│   │   ├── home.html
│   │   ├── product.html
│   │   ├── cart.html
│   │   └── order.html
│   ├── package.json
│   └── experiment.json
└── ... (weitere Funktionen)
```

---

## 5. Microservices Build-Prozess (microservices/build.js)

### 5.1 Überblick

Der Microservices-Build gruppiert Funktionen in logische Services. Jeder Service ist ein eigenständiger Express-Server mit Docker-Deployment.

### 5.2 Service-Definition

```javascript
const services = {
  'cart-service': {
    functions: ['getcart', 'addcartitem', 'emptycart', 'cartkvstorage'],
    dependencies: {
      '@befaas/lib': '*',
      'express': '^4.18.2',
      'ioredis': '^5.3.2',
      'aws-jwt-verify': '^4.0.0',
      ...
    },
    port: 3002
  },
  'content-service': {
    functions: ['getads', 'supportedcurrencies', 'currency'],
    copyCurrencyModule: true,  // Benötigt exchangerates.js
    dependencies: { ... },
    port: 3004
  },
  'frontend-service': {
    functions: ['login', 'register'],
    copyFrontendHandlers: true,  // Benötigt handlers.js und Templates
    dependencies: { ... },
    port: 3000
  },
  'order-service': {
    functions: ['checkout', 'payment', 'shipmentquote', 'shiporder', 'email'],
    dependencies: { ... },
    port: 3003
  },
  'product-service': {
    functions: ['getproduct', 'listproducts', 'searchproducts', 'listrecommendations'],
    copyProductCatalog: true,  // Benötigt products.js
    dependencies: { ... },
    port: 3001
  }
};
```

### 5.3 Schritte für jeden Service

#### Schritt 1: Service-Verzeichnis erstellen
```javascript
const serviceDir = path.join(tmpDir, serviceName);
const functionsDir = path.join(serviceDir, 'functions');
fs.mkdirSync(functionsDir, { recursive: true });
```

#### Schritt 2: Service-Index kopieren
```javascript
// Jeder Service hat einen eigenen Express-Server
fs.copyFileSync(
  path.join(__dirname, serviceName, 'index.js'),
  path.join(serviceDir, 'index.js')
);
```

#### Schritt 3: Dockerfile generieren/kopieren
```javascript
function copyDockerfile(serviceName, serviceDir) {
  const dockerfileSrc = path.join(__dirname, serviceName, 'Dockerfile');
  if (fs.existsSync(dockerfileSrc)) {
    fs.copyFileSync(dockerfileSrc, path.join(serviceDir, 'Dockerfile'));
  } else {
    // Standard-Dockerfile generieren
    const defaultDockerfile = `
FROM node:18-alpine AS base
FROM base AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci --only=production
FROM base AS runner
WORKDIR /app
COPY --from=builder /app/node_modules ./node_modules
COPY . .
ENV PORT=${services[serviceName].port}
EXPOSE ${services[serviceName].port}
CMD ["node", "index.js"]
`;
    fs.writeFileSync(path.join(serviceDir, 'Dockerfile'), defaultDockerfile);
  }
}
```

#### Schritt 4: Funktionen zum Service kopieren
```javascript
function copyFunctionToService(functionName, serviceDir, authStrategy) {
  const functionDir = path.join(serviceDir, 'functions', functionName);
  fs.mkdirSync(functionDir, { recursive: true });

  // Auth-Override für 'none' Strategie
  let srcPath;
  if (authStrategy === 'none' && ['login', 'register'].includes(functionName)) {
    const mockHandlerPath = path.join(authStrategyDir, `${functionName}.js`);
    if (fs.existsSync(mockHandlerPath)) {
      srcPath = mockHandlerPath;
    }
  } else {
    srcPath = path.join(functionsDir, functionName, 'index.js');
  }

  fs.copyFileSync(srcPath, path.join(functionDir, 'index.js'));

  // Auth-Dateien in Funktionsverzeichnis kopieren (für require('./auth'))
  if (content.includes("require('./auth')")) {
    fs.copyFileSync(
      path.join(authStrategyDir, 'index.js'),
      path.join(functionDir, 'auth.js')
    );
  }
}
```

#### Schritt 5: Service-spezifische Module kopieren
```javascript
// Currency-Modul für content-service
if (serviceConfig.copyCurrencyModule) {
  fs.copyFileSync(
    path.join(__dirname, '..', '..', 'currency', 'exchangerates.js'),
    path.join(serviceDir, 'currency', 'exchangerates.js')
  );
}

// Produktkatalog für product-service
if (serviceConfig.copyProductCatalog) {
  fs.copyFileSync(
    path.join(__dirname, '..', '..', 'productcatalog', 'products.js'),
    path.join(serviceDir, 'productcatalog', 'products.js')
  );
}

// Frontend-Handler und Templates für frontend-service
if (serviceConfig.copyFrontendHandlers) {
  copyFrontendHandlers(serviceDir);
}
```

#### Schritt 6: Shared-Module kopieren
```javascript
function copySharedModules(serviceDir) {
  // Microservices-spezifische Shared-Dateien
  const sharedSrcDir = path.join(__dirname, 'shared');
  copyDirectory(sharedSrcDir, path.join(serviceDir, 'shared'));

  // Architektur-übergreifende Shared-Dateien
  const archSharedFiles = ['call.js', 'serviceConfig.js', 'authConfig.js'];
  archSharedFiles.forEach(file => {
    fs.copyFileSync(
      path.join(__dirname, '..', 'shared', file),
      path.join(serviceDir, 'shared', 'arch-shared', file)
    );
  });
}
```

#### Schritt 7: Auth-Strategie kopieren
```javascript
function copyAuthStrategy(serviceDir, authStrategy) {
  const authDir = path.join(serviceDir, 'auth');
  fs.mkdirSync(authDir, { recursive: true });

  const authFiles = fs.readdirSync(authStrategyDir);
  authFiles.forEach(file => {
    fs.copyFileSync(
      path.join(authStrategyDir, file),
      path.join(authDir, file)
    );
  });
}
```

#### Schritt 8: Package.json generieren
```javascript
const packageJson = {
  name: serviceName,
  version: '1.0.0',
  description: `${serviceName} microservice`,
  main: 'index.js',
  dependencies: serviceConfig.dependencies,
  scripts: { start: 'node index.js' }
};
fs.writeFileSync(
  path.join(serviceDir, 'package.json'),
  JSON.stringify(packageJson, null, 2)
);
```

### 5.4 Output-Struktur (Microservices)

```
_build/
├── cart-service/
│   ├── index.js          # Express-Server
│   ├── Dockerfile
│   ├── package.json
│   ├── auth/
│   │   └── index.js
│   ├── shared/
│   │   ├── call.js
│   │   ├── libConfig.js
│   │   └── arch-shared/
│   │       ├── authConfig.js
│   │       ├── call.js
│   │       └── serviceConfig.js
│   └── functions/
│       ├── getcart/
│       │   ├── index.js
│       │   └── auth.js
│       ├── addcartitem/
│       │   ├── index.js
│       │   └── auth.js
│       ├── emptycart/
│       │   └── index.js
│       └── cartkvstorage/
│           └── index.js
├── content-service/
│   ├── index.js
│   ├── Dockerfile
│   ├── package.json
│   ├── auth/
│   ├── shared/
│   ├── currency/
│   │   └── exchangerates.js
│   └── functions/
│       ├── getads/
│       ├── supportedcurrencies/
│       └── currency/
├── frontend-service/
│   ├── index.js
│   ├── Dockerfile
│   ├── package.json
│   ├── auth/
│   ├── shared/
│   └── functions/
│       ├── login/
│       ├── register/
│       └── frontend/
│           ├── handlers.js
│           └── html_templates/
├── order-service/
│   └── ... (ähnliche Struktur)
└── product-service/
    ├── ...
    └── productcatalog/
        └── products.js
```

---

## 6. Monolith Build-Prozess (monolith/build.js)

### 6.1 Überblick

Der Monolith-Build erstellt eine einzelne Anwendung mit allen Funktionen. Alle Funktionsaufrufe erfolgen in-process ohne Netzwerk-Overhead.

### 6.2 Build-Schritte

#### Schritt 1: Verzeichnis erstellen
```javascript
if (!fs.existsSync(tmpDir)) {
  fs.mkdirSync(tmpDir, { recursive: true });
}
```

#### Schritt 2: Server-Dateien kopieren
```javascript
// Haupt-Server (Koa)
fs.copyFileSync(
  path.join(__dirname, 'index.js'),
  path.join(tmpDir, 'index.js')
);

// Monolith-Call-Provider
fs.copyFileSync(
  path.join(__dirname, 'call.js'),
  path.join(tmpDir, 'call.js')
);

// Package.json
fs.copyFileSync(
  path.join(__dirname, 'package.json'),
  path.join(tmpDir, 'package.json')
);

// Dockerfile
fs.copyFileSync(
  path.join(__dirname, 'Dockerfile'),
  path.join(tmpDir, 'Dockerfile')
);
```

#### Schritt 3: Alle Funktionen kopieren
```javascript
const functionNames = fs.readdirSync(sourceFunctionsDir).filter(file => {
  return fs.statSync(path.join(sourceFunctionsDir, file)).isDirectory();
});

functionNames.forEach(functionName => {
  // Rekursiv kopieren (inkl. Unterverzeichnisse wie html_templates)
  copyDirRecursive(
    path.join(sourceFunctionsDir, functionName),
    path.join(tmpDir, 'functions', functionName)
  );

  // Auth-Override für 'none' Strategie
  if (authStrategy === 'none' && ['login', 'register'].includes(functionName)) {
    const mockHandlerPath = path.join(authStrategyDir, `${functionName}.js`);
    if (fs.existsSync(mockHandlerPath)) {
      fs.copyFileSync(
        mockHandlerPath,
        path.join(tmpDir, 'functions', functionName, 'index.js')
      );
    }
  }

  // Auth-Dateien in jede Funktion kopieren
  authFiles.forEach(file => {
    fs.copyFileSync(
      path.join(authStrategyDir, file),
      path.join(tmpDir, 'functions', functionName, 'auth', file)
    );
  });
});
```

#### Schritt 4: Auth-Strategie auf Root-Level kopieren
```javascript
authFiles.forEach(file => {
  fs.copyFileSync(
    path.join(authStrategyDir, file),
    path.join(tmpDir, 'auth', file)
  );
});
```

#### Schritt 5: Datenmodule kopieren
```javascript
// Produktkatalog
copyDirRecursive(
  path.join(__dirname, '..', '..', 'productcatalog'),
  path.join(tmpDir, 'productcatalog')
);

// Währungsdaten
copyDirRecursive(
  path.join(__dirname, '..', '..', 'currency'),
  path.join(tmpDir, 'currency')
);
```

#### Schritt 6: Shared-Utilities kopieren
```javascript
copyDirRecursive(
  path.join(__dirname, '..', 'shared'),
  path.join(tmpDir, 'shared')
);
```

### 6.3 Output-Struktur (Monolith)

```
_build/
├── index.js              # Koa-Server mit allen Routen
├── call.js               # MonolithCallProvider
├── package.json
├── Dockerfile
├── auth/
│   └── index.js          # Auth-Strategie (Root-Level)
├── shared/
│   ├── authConfig.js
│   ├── call.js
│   └── serviceConfig.js
├── productcatalog/
│   └── products.js
├── currency/
│   └── exchangerates.js
└── functions/
    ├── addcartitem/
    │   ├── index.js
    │   └── auth/
    │       └── index.js
    ├── cartkvstorage/
    │   ├── index.js
    │   └── auth/
    ├── checkout/
    │   ├── index.js
    │   └── auth/
    ├── currency/
    │   ├── index.js
    │   └── auth/
    ├── frontend/
    │   ├── index.js
    │   ├── handlers.js
    │   ├── html_templates/
    │   │   ├── home.html
    │   │   ├── product.html
    │   │   ├── cart.html
    │   │   └── order.html
    │   └── auth/
    └── ... (alle weiteren Funktionen)
```

---

## 7. Call-Provider-Architektur

### 7.1 Gemeinsame Basisklasse (shared/call.js)

```javascript
class BaseCallProvider {
  constructor(options = {}) {
    this.authHeader = options.authHeader || null;
  }

  async call(functionName, payload) {
    throw new Error('call() must be implemented');
  }

  canCallLocally(functionName) { return false; }
  canDirectInvoke(functionName) { return false; }
}
```

### 7.2 FaaS Call-Provider (faas/call.js)

**Call-Strategie:**
1. AWS Lambda-zu-Lambda: Direkte Invokation (umgeht API Gateway)
2. Cross-Provider oder Fallback: HTTP via API Gateway

```javascript
class FaaSCallProvider extends BaseCallProvider {
  async call(functionName, payload) {
    const provider = experiment.program.functions[functionName].provider;

    // Direkte Lambda-Invokation für AWS-Targets
    if (provider === 'aws' && isDirectInvokeAvailable(functionName)) {
      return await directInvoke(functionName, payload, headers);
    }

    // Fallback zu HTTP via API Gateway
    const endpoint = `${endpoints[provider]}/${functionName}/call`;
    const res = await fetch(endpoint, {
      method: 'post',
      body: JSON.stringify(payload),
      headers
    });
    return res.json();
  }
}
```

**Direkte Lambda-Invokation:**
```javascript
async function directInvoke(fn, payload, headers) {
  const functionName = process.env[`LAMBDA_FN_${fn.toUpperCase()}`];

  const event = {
    version: '2.0',
    routeKey: 'POST /call',
    headers: { 'content-type': 'application/json', ...headers },
    body: JSON.stringify(payload),
    isBase64Encoded: false
  };

  const command = new InvokeCommand({
    FunctionName: functionName,
    InvocationType: 'RequestResponse',
    Payload: JSON.stringify(event)
  });

  const response = await lambdaClient.send(command);
  return JSON.parse(Buffer.from(response.Payload).toString());
}
```

### 7.3 Microservices Call-Provider (microservices/shared/call.js)

**Call-Strategie:**
1. Same-Service: Direkte In-Process-Aufrufe
2. Cross-Service: HTTP via Docker-DNS oder AWS Cloud Map

```javascript
class MicroservicesCallProvider extends BaseCallProvider {
  canCallLocally(functionName) {
    const targetService = getServiceForFunction(functionName);
    return (
      this.currentService &&
      targetService === this.currentService &&
      !!localHandlers[functionName]
    );
  }

  async call(functionName, payload) {
    // Same-Service: In-Process
    if (this.canCallLocally(functionName)) {
      return await localHandlers[functionName](payload);
    }

    // Cross-Service: HTTP
    const endpoint = getFunctionEndpoint(functionName);
    const response = await axios.post(endpoint, payload, { headers });
    return response.data;
  }
}
```

**Service-URL-Auflösung:**
```javascript
const serviceUrls = isAWS ? {
  // AWS Cloud Map DNS
  cart: `http://cart-service.${namespace}:3002`,
  product: `http://product-service.${namespace}:3001`,
  ...
} : {
  // Docker Compose
  cart: process.env.CART_SERVICE_URL || 'http://cart-service:3002',
  ...
};
```

### 7.4 Monolith Call-Provider (monolith/call.js)

**Call-Strategie:**
- Immer: Direkte In-Process-Aufrufe (kein Netzwerk)

```javascript
class MonolithCallProvider extends BaseCallProvider {
  canCallLocally(functionName) {
    return !!localHandlers[functionName];
  }

  async call(functionName, payload) {
    const handler = localHandlers[functionName];
    if (!handler) {
      throw new Error(`Function not found: ${functionName}`);
    }

    const innerCtx = createCallContext(this.authHeader);
    return await handler(payload, innerCtx);
  }
}
```

**Handler-Registrierung:**
```javascript
// In monolith/index.js
registerHandlers({
  addcartitem: require('./functions/addcartitem'),
  cartkvstorage: require('./functions/cartkvstorage'),
  checkout: require('./functions/checkout'),
  ...
});
```

---

## 8. Authentifizierungs-Konfiguration

### 8.1 authConfig.js - Funktions-Klassifizierung

```javascript
// Funktionen, die JWT-Authentifizierung erfordern
const authRequiredFunctions = new Set([
  'getcart',
  'addcartitem',
  'emptycart',
  'cartkvstorage',
  'checkout',
  'payment'
]);

// Öffentliche Funktionen (keine Auth erforderlich)
const publicFunctions = new Set([
  'listproducts',
  'getproduct',
  'searchproducts',
  'listrecommendations',
  'getads',
  'supportedcurrencies',
  'currency',
  'shipmentquote',
  'shiporder',
  'email',
  'frontend',
  'login',
  'register'
]);

function requiresAuth(functionName) {
  return authRequiredFunctions.has(functionName);
}
```

### 8.2 Auth-Strategien

**service-integrated (Cognito JWT):**
```javascript
const { CognitoJwtVerifier } = require('aws-jwt-verify');

async function verifyJWT(event, contextId) {
  const authHeader = event.headers?.authorization;
  if (!authHeader) return false;

  const token = authHeader.replace(/^Bearer\s+/i, '');
  const verifier = CognitoJwtVerifier.create({
    userPoolId: process.env.COGNITO_USER_POOL_ID,
    tokenUse: 'access',
    clientId: process.env.COGNITO_CLIENT_ID
  });

  const payload = await verifier.verify(token);
  return payload;
}
```

**none (No-Op):**
```javascript
async function verifyJWT() {
  return true;
}
```

---

## 9. serviceConfig.js - Funktion-zu-Service-Mapping

Definiert die logische Gruppierung von Funktionen zu Services (hauptsächlich für Microservices relevant):

```javascript
const functionToService = {
  // Cart Service
  'cartkvstorage': 'cart',
  'getcart': 'cart',
  'addcartitem': 'cart',
  'emptycart': 'cart',

  // Product Service
  'getproduct': 'product',
  'listproducts': 'product',
  'searchproducts': 'product',
  'listrecommendations': 'product',

  // Order Service
  'checkout': 'order',
  'payment': 'order',
  'shiporder': 'order',
  'shipmentquote': 'order',
  'email': 'order',

  // Content Service
  'getads': 'content',
  'supportedcurrencies': 'content',
  'currency': 'content',

  // Frontend Service
  'frontend': 'frontend',
  'login': 'frontend',
  'register': 'frontend'
};
```

---

## 10. Zusammenfassung der Build-Unterschiede

| Aspekt | FaaS | Microservices | Monolith |
|--------|------|---------------|----------|
| **Deployment-Einheiten** | Eine pro Funktion | Eine pro Service | Eine gesamt |
| **Netzwerk-Overhead** | Ja (Lambda Invoke/HTTP) | Teils (Cross-Service) | Nein |
| **Code-Duplizierung** | Hoch (jede Funktion autark) | Mittel (pro Service) | Niedrig |
| **Skalierungseinheit** | Einzelne Funktion | Service | Gesamte Anwendung |
| **Auth-Integration** | restHandler.js | Service-Index | Server-Middleware |
| **Call-Provider** | FaaSCallProvider | MicroservicesCallProvider | MonolithCallProvider |
| **Pfad-Transformation** | Ja (../../ -> ./) | Nein | Nein |

---

## 11. Build-Aufruf

Alle Build-Skripte folgen demselben Interface:

```javascript
// Programmatisch
const build = require('./build');
await build(outputDir, authStrategy, bundleMode);

// Kommandozeile
node build.js <authStrategy> <outputDir>
// Beispiel:
node experiments/webservice/architectures/faas/build.js service-integrated ./_build
```

**Parameter:**
- `authStrategy`: 'none', 'service-integrated', 'service-integrated-manual'
- `outputDir`: Zielverzeichnis für das Build-Ergebnis
- `bundleMode` (nur FaaS): 'minimal' (experiment.json) oder 'all'