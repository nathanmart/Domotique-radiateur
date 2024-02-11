import paho.mqtt.client as mqtt

class MQTTClient:

    def __init__(self, broker_address, broker_port=1883):
        self.client = mqtt.Client()
        self.client.connect(broker_address, broker_port)
        self.message_recu = None

    def publish(self, message, topic):
        self.client.publish(topic, message)

    def subscribe(self, topic):
        self.client.on_message = self.on_message
        self.client.subscribe(topic)
        self.client.loop_start()

    def on_message(self, client, userdata, message):
        self.message_recu = message.payload.decode('utf-8')

    def unsubscribe(self):
        self.client.loop_stop()
        return 1

    def get_message_recu(self):
        return self.message_recu

    def reset_message_recu(self):
        self.message_recu = None
        return 1