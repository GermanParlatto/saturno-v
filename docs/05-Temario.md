# WAKU-CODE — Temario Python del Curso
## Proyecto Waku-Code · Documento 5
### Contenido programático detallado (Levels 0–3 + Proyecto Final + Expansiones)

---

## 📋 Estructura general

- **Público**: niños y adolescentes de 10–14 años, sin experiencia previa.
- **Canal**: WhatsApp (texto + foto de ejercicios a mano con OCR).
- **Progresión**: 4 niveles secuenciales (ningún nivel se salta) + proyecto final + expansiones.
- **Formato por concepto**: analogía del Lore → **término real** → código visible →
  ejercicio (PRIMM: predecir antes de escribir).
- **Tipos de ejercicio por nivel**: seleccionar opción · escribir código · resolver a
  mano en papel (foto/OCR).

---

## 🛰️ LEVEL 0 — Definiciones
### Misión: El Despertar de la Nave · Rango: Cadete Estelar

- **Objetivo del nivel**: entender qué es programar antes de escribir código; instalar el
  modelo mental de «instrucciones exactas, en orden».
- **Conceptos**:
  - **Qué es un lenguaje de programación**
    - Diferencia entre hablarle a una persona (interpreta) y a una computadora (obedece literal).
    - Ejemplos cotidianos de instrucciones (recetas, rutas, reglas de juego).
  - **Qué es un algoritmo**
    - Definición: secuencia finita de pasos exactos y ordenados.
    - Propiedades: el orden importa, la precisión importa, mismo inicio → mismo resultado.
    - Ejercicio insignia: **Proyecto post-it (Proyecto Sandwich)** — escribir en papel los
      pasos para hacer un sándwich; Spoky los ejecuta «al pie de la letra» evidenciando
      ambigüedades.
  - **Sintaxis básica de Python (reglas de escritura)**
    - Sensibilidad a mayúsculas/minúsculas (`edad` ≠ `Edad`).
    - Paréntesis, comillas y dos puntos: dónde van y por qué.
    - Errores de sintaxis: qué son y cómo leer el mensaje de la nave.
    - Primer programa: `print("Hola Spoky")`.
- **Vocabulario real que se instala**: programa, instrucción, algoritmo, sintaxis, error.
- **Clímax evaluable**: escribir un algoritmo en papel (foto) + ejecutar su primer `print()`.

---

## 🔋 LEVEL 1 — Variables y tipos de datos
### Misión: Los Contenedores de Energía · Rango: Técnico de Energía

- **Objetivo del nivel**: almacenar, leer y transformar datos; comunicarse con el programa.
- **Conceptos**:
  - **`print()` — salida**
    - Imprimir textos, números y varios elementos.
    - Imprimir el valor de una variable vs. imprimir texto literal.
  - **`input()` — entrada**
    - Capturar lo que escribe el usuario.
    - ⚠️ Punto de ruptura obligatorio: `input()` **siempre devuelve `str`**, aunque el
      usuario escriba un número.
  - **Variables**
    - Crear (`nombre = "Aria"`), leer y **reasignar**.
    - **Ley del Cristal Único**: la reasignación desintegra el valor anterior
      (`x = 5` → `x = 7` → solo existe 7). Prevención explícita de la misconception de
      «valores múltiples».
    - Reglas de nombrado: sin espacios, sin empezar con número, nombres descriptivos.
    - Diferencia crítica: `=` asigna, no es el «igual» matemático.
  - **Tipos de datos**
    - `int` (enteros), `float` (decimales), `str` (texto).
    - Por qué la nave los distingue: `"5" + "3"` vs `5 + 3`.
    - Función `type()` como «escáner de cristales» (opcional/refuerzo).
  - **Conversión de tipos**
    - `int(input(...))`, `float(...)`, `str(...)`.
    - ⚠️ Punto de ruptura: `int("hola")` falla — la conversión debe tener sentido.
  - **Operadores aritméticos**
    - `+`, `-`, `*`, `/`.
    - Precedencia básica con paréntesis.
    - Concatenación de textos con `+` (unir cristales de palabras).
- **Vocabulario real**: variable, valor, tipo de dato, asignación, conversión, operador.
- **Clímax evaluable**: programa que pregunta nombre y edad, convierte la edad, calcula la
  «edad de cadete» (p. ej. edad + 100) y saluda — la nave conoce a su copiloto.

---

## 🧭 LEVEL 2 — Condicionales
### Misión: El Navegador Estelar · Rango: Navegante

- **Objetivo del nivel**: que el programa tome decisiones según condiciones.
- **Conceptos**:
  - **Booleanos**
    - `True` / `False` como únicas respuestas de los sensores.
  - **Operadores de comparación**
    - `>`, `<`, `>=`, `<=`, `==`, `!=`.
    - ⚠️ Punto de ruptura obligatorio: `==` compara, `=` asigna — el error más común del nivel.
  - **`if` / `elif` / `else`**
    - Estructura, dos puntos e **indentación** como definición de bloque (la «zona de mando»).
    - **Ley de la Ruta Única**: se evalúa en orden y se ejecuta una sola rama.
    - Orden de las condiciones: por qué `elif edad > 10` antes de `elif edad > 5` cambia todo.
  - **Operadores lógicos**
    - `and`, `or` (sensores combinados); `not` como extensión opcional.
    - Tablas de verdad en versión juego (predicción tipo PRIMM).
  - **Condicionales anidados** (extensión opcional, solo si el nivel va sobrado).
- **Vocabulario real**: condición, booleano, comparación, bloque, indentación, rama.
- **Clímax evaluable**: mini-misión **«El Cinturón de Asteroides»** — programa que lee
  datos de sensores (`input`) y decide la ruta con `if/elif/else` + `and`/`or`.

---

## 🚀 LEVEL 3 — Ciclos
### Misión: Los Motores de Salto · Rango: Ingeniero de Salto

- **Objetivo del nivel**: repetir instrucciones sin duplicar código; controlar cuándo
  termina la repetición.
- **Conceptos**:
  - **`while`**
    - Estructura: condición → cuerpo → **actualización de la variable de control**.
    - **Ley de la Condición de Salida**: bucle infinito = motor atascado; todo `while` se
      revisa preguntando «¿qué hace que termine?».
    - Patrón contador (`intentos = intentos + 1`).
    - Uso típico: repetir hasta respuesta válida (validar `input`).
  - **`for`**
    - `for i in range(...)`: inicio, fin, paso; la cuenta regresiva de despegue
      (`range(10, 0, -1)`).
    - Recorrer un `str` letra a letra (extensión).
    - Cuándo `for` y cuándo `while`: repeticiones contadas vs. condicionadas.
  - **Patrones combinados**
    - Contador y acumulador (sumar puntos de energía).
    - Bucle + condicional dentro (revisar cada pieza y decidir).
- **Vocabulario real**: bucle, iteración, condición de salida, contador, acumulador, rango.
- **Clímax evaluable**: los motores rugen — programa con `while` de validación + `for` de
  ignición repetida.

---

## 🏁 PROYECTO FINAL — El Despegue (integra todo)
### Rango: Piloto Estelar

- **Programa de despegue** que combina los 4 niveles:
  - `input()` + conversión → datos del copiloto (variables, tipos).
  - `if/elif/else` + lógicos → verificación de sistemas antes de despegar.
  - `while` → reintentar si un dato es inválido.
  - `for` → cuenta regresiva 10…0 y `print("¡DESPEGUE! 🚀")`.
- **Evaluación**: rúbrica por concepto (LLM as Judge) + explicación del alumno de qué hace
  cada parte (comprensión, no solo ejecución — PRIMM/Investigate).

---

## 🌌 EXPANSIONES (temporadas futuras — fuera del MVP)

- **Funciones** («Módulos de la nave»): `def`, parámetros, `return`, reutilización.
- **Listas** («Bodega de Carga»): crear, indexar, `append()`, recorrer con `for`, `len()`.
- **Errores y depuración** («Taller de Reparaciones»): leer tracebacks, errores comunes
  (`SyntaxError`, `TypeError`, `NameError`), estrategia de depuración paso a paso.
- **Proyecto libre** («Nave propia»): el alumno diseña su primer programa completo ligado
  al sueño declarado en su Juramento del Cadete.

---

## Nota de trazabilidad

Este temario respeta el alcance del board del proyecto (Levels 0–3, «Alcance del Contenido
del Curso – Python») y explicita lo que estaba implícito: booleanos, indentación,
`input()` → str, `==` vs `=`, y los patrones contador/acumulador. Son los puntos donde la
investigación de misconceptions en novatos indica mayor riesgo de error, y cada uno tiene
su correspondencia en la tabla de **puntos de ruptura de analogías** (Documento 3) y en
las **Leyes Físicas de Waku-9** (Documento 2).
