// Sends "PRESSED" when the button on pin 2 is pressed, and "DIM <0-100>"
// when the potentiometer on A0 is turned. Reports "KNOB <0-100>" at startup.
const int BUTTON_PIN = 2;
const int POT_PIN = A0;
const unsigned long DEBOUNCE_MS = 50;
const int DIM_STEP = 2;  // ignore 1% wobble from ADC noise; the Pi smooths the steps

int lastReading = HIGH;
int stableState = HIGH;
unsigned long lastChange = 0;
int lastDim;

int readDim() {
  long sum = 0;
  for (int i = 0; i < 32; i++) sum += analogRead(POT_PIN);  // average out noise
  return map(sum / 32, 0, 1023, 0, 100);
}

void setup() {
  pinMode(BUTTON_PIN, INPUT_PULLUP);  // pressed = LOW
  pinMode(LED_BUILTIN, OUTPUT);
  Serial.begin(9600);
  lastDim = readDim();  // don't change the lights just because the Uno restarted
  Serial.println("READY");
  Serial.print("KNOB ");  // tell the Pi where the knob is without changing the lights
  Serial.println(lastDim);
}

void loop() {
  int reading = digitalRead(BUTTON_PIN);
  if (reading != lastReading) {
    lastChange = millis();
    lastReading = reading;
  }
  if (millis() - lastChange > DEBOUNCE_MS && reading != stableState) {
    stableState = reading;
    digitalWrite(LED_BUILTIN, stableState == LOW);
    if (stableState == LOW) Serial.println("PRESSED");
  }

  int dim = readDim();
  bool atEnd = (dim == 0 || dim == 100) && dim != lastDim;
  if (abs(dim - lastDim) >= DIM_STEP || atEnd) {
    lastDim = dim;
    Serial.print("DIM ");
    Serial.println(dim);
  }
  delay(10);
}
